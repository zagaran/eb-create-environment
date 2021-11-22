import time
import boto3

from datetime import timedelta, datetime
from botocore.exceptions import ParamValidationError
from choicesenum import ChoicesEnum
from eb_create_environment.utils import generate_secure_password
from eb_create_environment.vpc import VPCAccessor


BASE_PARAMS = [
    'AllocatedStorage',
    'DBInstanceClass',
    'MasterUsername',
    'BackupRetentionPeriod',
    'MultiAZ',
    'AutoMinorVersionUpgrade',
    'PubliclyAccessible',
    'StorageType',
    'StorageEncrypted',
    'CopyTagsToSnapshot',
    'MonitoringInterval',
    'DeletionProtection',
    'MaxAllocatedStorage',
]

# Currently not in use
EXTENDED_PARAMS = dict(
    AvailabilityZone='string',
    PreferredMaintenanceWindow='string',
    PreferredBackupWindow='string',
    Iops=0,
    DBClusterIdentifier='string',
    Tags=[
        {
            'Key': 'string',
            'Value': 'string'
        },
    ],
    EnableCustomerOwnedIp=False,
    OptionGroupName='string',
    CharacterSetName='string',
    TdeCredentialArn='string',
    TdeCredentialPassword='string',
    KmsKeyId='string',
    ProcessorFeatures=[
        {
            'Name': 'string',
            'Value': 'string'
        },
    ],
    EnableCloudwatchLogsExports=[
        'string',
    ],
    PerformanceInsightsKMSKeyId='string',
    PerformanceInsightsRetentionPeriod=7,
    Domain='string',
    MonitoringRoleArn='string',
    DomainIAMRoleName='string',
    PromotionTier=123,  # aurora
    Timezone='string',  # sqlserver
    EnableIAMDatabaseAuthentication=True | False,
    EnablePerformanceInsights=True | False,
)

POSTGRES_PARAMS = [
    'DBName',
    'Engine',
    'EngineVersion',
    'Port',
    'DBParameterGroupName',
    'LicenseModel',
]

ORACLE_PARAMS = [
    'DBName',
    'Engine',
    'EngineVersion',
    'Port',
    'DBParameterGroupName',
    'LicenseModel',
    'NcharCharacterSetName',
]


class Engine(ChoicesEnum):
    postgres = "postgres"
    oracle = "oracle"


PARAMS_BY_ENGINE = {
    Engine.postgres: POSTGRES_PARAMS,
}

ENGINE_NAME_LOOKUP = {
    Engine.postgres: "Postgres",
}


class DatabaseInitializer(object):
    def __init__(self, region, config, engine, vpc_id, environment_name, application_security_group_id):
        self.region = region

        self.password = generate_secure_password()
        self.engine = engine
        self.config = config

        self.client = boto3.client("rds", self.region)
        self.vpc_id = vpc_id
        self.vpc_subnet = ""  # TODO: this
        self.environment_name = environment_name
        self.db_name = f"{self.environment_name}-db"
        self.application_security_group_id = application_security_group_id

    def create_db_security_group(self):
        ec2_client = boto3.client('ec2', self.region)
        security_group_name = f"{self.environment_name}-db"
        response = ec2_client.create_security_group(
            GroupName=security_group_name,
            Description=f"Database security group for {self.environment_name}",
            VpcId=self.vpc_id,
            TagSpecifications=[{
                "ResourceType": "security-group",
                "Tags": [{"Key": "Name", "Value": security_group_name}]
            }]
        )
        security_group_id = response['GroupId']
        port = self.get_config_params()["Port"]
        ec2_client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {'IpProtocol': 'tcp',
                 'FromPort': port,
                 'ToPort': port,
                 'UserIdGroupPairs': [{'GroupId': self.application_security_group_id}]},
            ]
        )
        return security_group_id

    def create_db(self):
        vpc_security_groups = [self.create_db_security_group()]
        db_subnet_group = self.get_db_subnet_group()
        if not db_subnet_group:
            db_subnet_group = self.create_db_subnet_group()
        try:
            params = dict(
                DBInstanceIdentifier=self.db_name,
                MasterUserPassword=self.password,
                # DBSecurityGroups=db_security_groups,
                VpcSecurityGroupIds=vpc_security_groups,
                DBSubnetGroupName=db_subnet_group,
                **self.get_config_params(),
            )
            self.client.create_db_instance(**params)
        except ParamValidationError:
            print(self.get_config_params())
            raise
        host = self.get_host_from_response()
        print("Waiting for Database")
        return self.get_db_url(params['MasterUsername'], host, params['Port'])

    def get_config_params(self):
        config_engine_name = ENGINE_NAME_LOOKUP[self.engine]
        base_params = {
            param: self.config['RDS'][param] for param in BASE_PARAMS
        }
        engine_params = {
            param: self.config['RDS'][config_engine_name][param] for param in PARAMS_BY_ENGINE[self.engine]
        }
        return {
            **base_params,
            **engine_params,
        }

    def get_db_url(self, user, host, port):
        postgres_db_name = self.config["RDS"]["Postgres"]["DBName"]
        if self.engine == Engine.postgres:
            return f"postgres://{user}:{self.password}@{host}:{port}/{postgres_db_name}?sslmode=require"
        else:
            return ""

    def get_host_from_response(self):
        timeout = timedelta(minutes=15)
        start = datetime.now()
        host = ""
        while True:
            if datetime.now() > start + timeout:
                break
            response = self.client.describe_db_instances()
            for db in response['DBInstances']:
                if db['DBInstanceIdentifier'] == self.db_name:
                    try:
                        host = db['Endpoint']['Address'] or ""
                    except:
                        pass
            if host:
                break
            time.sleep(10)
        return host

    def get_db_subnet_group(self):
        response = self.client.describe_db_subnet_groups()
        if 'DBSubnetGroups' in response:
            vpc_subnet_groups = [
                subnet_group['DBSubnetGroupName'] for subnet_group in response['DBSubnetGroups']
                if subnet_group['VpcId'] == self.vpc_id
            ]
            if vpc_subnet_groups:
                return vpc_subnet_groups[0]
        return None
    
    def create_db_subnet_group(self):
        vpc = VPCAccessor(self.region)
        subnet_ids = list(vpc.get_subnets(self.vpc_id))
        subnet_group_name = f"default-{self.vpc_id}"
        self.client.create_db_subnet_group(
            DBSubnetGroupName=subnet_group_name,
            DBSubnetGroupDescription=f"All subnets for {self.vpc_id}",
            SubnetIds=subnet_ids,
        )
        return subnet_group_name
