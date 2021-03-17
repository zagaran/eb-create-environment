import boto3
from choicesenum import ChoicesEnum
from eb_create_environment.vpc import VPCAccessor
from botocore.exceptions import ParamValidationError


class ServerTier(ChoicesEnum):
    web = "web"
    worker = "worker"


class EBInitializer(object):
    
    def __init__(self, region, config, application_name, environment_name, cname_prefix, vpc_id, server_tier=ServerTier.web):
        self.region = region
        self.config = config
        
        self.application_name = application_name
        self.environment_name = environment_name
        self.cname_prefix = cname_prefix
        self.vpc_id = vpc_id
        self.server_tier = server_tier
    
    def get_eb_client(self):
        return boto3.client("elasticbeanstalk", self.region)
    
    def get_config_param(self, param_name, subname=None):
        try:
            if subname:
                return self.config["ElasticBeanstalk"][param_name][subname]
            return self.config["ElasticBeanstalk"][param_name]
        except KeyError:
            return None
    
    def set_up_environment(self):
        if self.server_tier == ServerTier.web:
            tier_config = {
                "Name": "WebServer",
                "Type": "Standard",
            }
        elif self.server_tier == ServerTier.worker:
            tier_config = {
                "Name": "Worker",
                "Type": "SQS/HTTP",
            }
        else:
            raise Exception(f"invalid server tier: {self.server_tier}")
        
        vpc_accessor = VPCAccessor(self.region)
        instance_subnets = vpc_accessor.get_subnets(self.vpc_id, self.get_config_param("InstancePublicSubnets"))
        if not instance_subnets:
            raise Exception("No valid subnets for instances")
        print(f"Using the following subnets for instances: {instance_subnets}")
        
        if self.get_config_param("LoadBalancer"):
            load_balancer_subnets = vpc_accessor.get_subnets(self.vpc_id, self.get_config_param("LoadBalancer", "PublicSubnets"))
            if not load_balancer_subnets:
                raise Exception("No valid subnets for the load balancer")
            print(f"Using the following subnets for the load balancer: {load_balancer_subnets}")
        
        options = {
            ("aws:elasticbeanstalk:container:python", "NumProcesses"): str(self.get_config_param("NumProcesses")),
            ("aws:ec2:instances", "InstanceTypes"): self.get_config_param("InstanceTypes"),
            ("aws:autoscaling:launchconfiguration", "IamInstanceProfile"): self.get_config_param("IamInstanceProfile"),
            ("aws:elasticbeanstalk:environment:proxy", "ProxyServer"): self.get_config_param("ProxyServer"),
            ("aws:ec2:vpc", "VPCId"): self.vpc_id,
            ("aws:ec2:vpc", "ELBSubnets"): ",".join(load_balancer_subnets),
            ("aws:ec2:vpc", "Subnets"): ",".join(instance_subnets),
            ("aws:ec2:vpc", "AssociatePublicIpAddress"): "true" if self.get_config_param("AssociatePublicIpAddress") else "false",
        }
        
        if self.get_config_param("LoadBalancer"):
            options[("aws:elasticbeanstalk:environment", "EnvironmentType")] = "LoadBalanced"
            options[("aws:elasticbeanstalk:environment", "LoadBalancerType")] = str(self.get_config_param("LoadBalancer", "LoadBalancerType"))
            options[("aws:elb:loadbalancer", "LoadBalancerHTTPPort")] = "80"
            options[("aws:autoscaling:asg", "MinSize")] = str(self.get_config_param("LoadBalancer", "MinSize"))
            options[("aws:autoscaling:asg", "MaxSize")] = str(self.get_config_param("LoadBalancer", "MaxSize"))
            options[("aws:ec2:vpc", "ELBScheme")] = self.get_config_param("LoadBalancer", "ELBScheme")
            # Health check should get modified after initial deploy
            options[("aws:elb:healthcheck", "Target")] = "/"
        else:
            options[("aws:elasticbeanstalk:environment", "EnvironmentType")] = "SingleInstance"
        
        if self.get_config_param("ManagedUpdates"):
            options[("aws:elasticbeanstalk:managedactions", "ManagedActionsEnabled")] = "true"
            options[("aws:elasticbeanstalk:managedactions", "PreferredStartTime")] = self.get_config_param("ManagedUpdates", "PreferredStartTime")
            options[("aws:elasticbeanstalk:managedactions", "ServiceRoleForManagedUpdates")] = self.get_config_param("ManagedUpdates", "ServiceRoleForManagedUpdates")
            options[("aws:elasticbeanstalk:managedactions:platformupdate", "UpdateLevel")] = self.get_config_param("ManagedUpdates", "UpdateLevel")
        else:
            options[("aws:elasticbeanstalk:managedactions", "ManagedActionsEnabled")] = "false"
        
        if self.get_config_param("LoadBalancer") and self.get_config_param("LoadBalancer", "SSLCertificateId"):
            options[("aws:elb:loadbalancer", "LoadBalancerHTTPSPort")] = "443"
            options[("aws:elb:loadbalancer", "SSLCertificateId")] = self.get_config_param("LoadBalancer", "SSLCertificateId")
        
        eb_client = self.get_eb_client()
        # Note that we don't pass VersionLabel to intentionally deploy the sample app
        option_settings = [{"Namespace": key[0], "OptionName": key[1], "Value": value} for key, value in options.items()]
        try:
            eb_client.create_environment(
                ApplicationName=self.application_name,
                EnvironmentName=self.environment_name,
                CNAMEPrefix=self.cname_prefix,
                Tier=tier_config,
                SolutionStackName=self.get_config_param("SolutionStackName"),
                OptionSettings=option_settings,
            )
        except ParamValidationError:
            for i, setting in enumerate(option_settings):
                print(i, setting)
            raise
    
    def wait_for_environment(self):
        eb_client = self.get_eb_client()
        waiter = eb_client.get_waiter('environment_exists')
        waiter.wait(
            ApplicationName=self.application_name,
            EnvironmentNames=[self.environment_name],
            IncludeDeleted=False,
            WaiterConfig={
                'Delay': 10,
                'MaxAttempts': 100
            }
        )
        env_resources = eb_client.describe_environment_resources(EnvironmentName=self.environment_name)
        launch_configuration_name = env_resources["EnvironmentResources"]["LaunchConfigurations"][0]["Name"]
        autoscaling_client = boto3.client("autoscaling", self.region)
        launch_configurations = autoscaling_client.describe_launch_configurations(LaunchConfigurationNames=[launch_configuration_name])
        return launch_configurations["LaunchConfigurations"][0]["SecurityGroups"][0]

    def update_environment_variables(self, environment_variable_mapping):
        option_settings = [
            {
                "Namespace": "aws:elasticbeanstalk:application:environment",
                "OptionName": variable,
                "Value": value,
            }
            for variable, value in environment_variable_mapping.items()
        ]
        return self.get_eb_client().update_environment(
            ApplicationName=self.application_name,
            EnvironmentName=self.environment_name,
            OptionSettings=option_settings
        )
