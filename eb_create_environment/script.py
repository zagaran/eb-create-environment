import argparse
import boto3
import os
import sys
import yaml

from eb_create_environment.database import DatabaseInitializer, Engine
from eb_create_environment.eb_setup import EBInitializer
from eb_create_environment.vpc import VPCAccessor


DEFAULT_CONFIG_FILE_PATH = "default_config.yml"
EB_GLOBAL_CONFIG_DIRECTORY = ".elasticbeanstalk"
EB_GLOBAL_CONFIG_FILE_PATH = os.path.join(EB_GLOBAL_CONFIG_DIRECTORY, "config.yml")


class SetupWrapper(object):
    def __init__(self):
        parser = argparse.ArgumentParser(description="Set up linked EB and RDS instances")
        parser.add_argument(
            "-c", "--config",
            default=None,
            help="Specify a custom config file",
        )
        parser.add_argument(
            "-a", "--application_name",
            default=None,
            help="Elastic Beanstalk application name",
        )
        parser.add_argument(
            "-e", "--environment_name",
            default=None,
            help="Elastic Beanstalk environment name",
        )
        parser.add_argument(
            "-p", "--profile",
            default=None,
            help="Specify an AWS profile from your credential file",
        )
        parser.add_argument(
            "-r", "--region",
            default=None,
            help="Specify an AWS region region",
        )
        parser.add_argument(
            "--db-only",
            default=False,
            action="store_true",
            help="Skip setup of application and environment. Requires application and environment to exist already."
        )
        parser.add_argument(
            "--no-db",
            default=False,
            action="store_true",
            help="Skip setup of the database.  Cannot be used with `--db-only`"
        )
        parser.add_argument(
            "--print-default-config",
            default=False,
            action="store_true",
            help="Print default config and exit"
        )
        args = parser.parse_args()
        if args.print_default_config:
            self.print_default_config()
            sys.exit()
        self.profile = args.profile
        self.application_name = args.application_name
        self.environment_name = args.environment_name
        self.region = args.region
        self.db_only = args.db_only
        self.no_db = args.no_db
        if self.db_only and self.no_db:
            raise Exception("--db-only cannot be used with --no-db")
        self.dir_path = os.path.dirname(os.path.realpath(__file__))
        self.config_file_path = args.config or os.path.join(self.dir_path, DEFAULT_CONFIG_FILE_PATH)
        # TODO: add support for application creation
        # self.create_new_application = False
        self.get_eb_config()

    def setup(self):
        # Read from config file
        config = self.parse_config_file()
        boto3.setup_default_session(profile_name=self.profile)
        # TODO: support worker tiers
        if not self.environment_name:
            self.environment_name = input("Input new environment name (lowercase-with-dashes): ")
        if self.db_only:
            cname_prefix = None
        else:
            cname_prefix = input("Input new CNAME prefix (lowercase-with-dashes): ")
        vpc_accessor = VPCAccessor(self.region)
        vpcs = vpc_accessor.get_vpcs()
        print("Current VPCS:")
        print(vpcs)
        if not(vpcs):
            raise Exception("No VPCs in that region")
        elif len(vpcs) == 1:
            vpc_id = list(vpcs.keys())[0]
            input(f"Using VPC {vpc_id}.  Press [Enter] to confirm ([Ctrl] + [C] to cancel)")
        else:
            vpc_id = input("Input vpc_id: ")
        eb_initializer = EBInitializer(self.region, config, self.application_name, self.environment_name, cname_prefix, vpc_id)
        if not self.db_only:
            print("\nLaunching EB environment")
            eb_initializer.set_up_environment()
            print("\nWaiting for EB environment to finish launching")
        application_security_group_id = eb_initializer.wait_for_environment()
        print("\nEB environment ready")
        
        if self.no_db:
            return
        
        # Call rds setup
        engine = Engine.postgres
        print("Setting up database")
        db_initializer = DatabaseInitializer(
            self.region, config, engine, vpc_id, self.environment_name, application_security_group_id
        )
        database_url = db_initializer.create_db()
        print("Database ready. Linking database to EB environment.")
        eb_initializer.update_environment_variables({
            "DATABASE_URL": database_url,
        })
        print("Environment setup complete.")
    
    def get_eb_config(self):
        """Parse eb config file if it exists. Otherwise, ask for user input and create file."""
        if os.path.isfile(EB_GLOBAL_CONFIG_FILE_PATH):
            with open(EB_GLOBAL_CONFIG_FILE_PATH) as config:
                global_configs = yaml.load(config, Loader=yaml.FullLoader)["global"]
            if not all(key in global_configs for key in ["application_name", "default_region", "profile"]):
                missing_keys = [
                    key for key in ["application_name", "default_region", "profile"] if key not
                    in global_configs
                ]
                raise Exception("MISSING GLOBAL CONFIG KEY(S): ", ", ".join(missing_keys))
            if not self.application_name:
                self.application_name = global_configs["application_name"]
            if not self.region:
                self.region = global_configs["default_region"]
            if not self.profile:
                self.profile = global_configs["profile"]
        
        current_profiles = boto3.session.Session().available_profiles
        if not self.profile:
            print("Current profiles")
            print(sorted(current_profiles))
            self.profile = input("Input profile: ")
        
        if self.profile not in current_profiles:
            raise Exception(f"Invalid profile {self.profile}")
        
        # Note that this must come after setting up profile so that we have the appropriate profile
        boto3.setup_default_session(profile_name=self.profile)
        ec2_client = boto3.client("ec2", "us-east-1")
        region_names = [i["RegionName"] for i in ec2_client.describe_regions()["Regions"]]
        if not self.region:
            print("AWS regions:")
            print(sorted(region_names))
            self.region = input("Input default region: ")
        if self.region not in region_names:
            raise Exception(f"Invalid region {self.region}")
        
        eb_client = boto3.client("elasticbeanstalk", self.region)
        current_applications = [i["ApplicationName"] for i in eb_client.describe_applications()["Applications"]]
        if not self.application_name:
            print("Current EB Applications:")
            print(sorted(current_applications))
            self.application_name = input("Input application name: ")
        if self.application_name not in current_applications:
            # TODO: create application if nonexistent
            # confirmation = input(f"Create new application named {self.application_name}? [y/n]")
            # if confirmation.lower().strip() in ["y", "yes"]:
            #     self.create_new_application = True
            # else:
            #     raise Exception(f"Invalid application name {self.application_name}")
            raise Exception(f"Invalid application name {self.application_name}")
        # Fill in config file if nonexistent
        if not os.path.isfile(EB_GLOBAL_CONFIG_FILE_PATH):
            self.create_eb_config_file()

        # Get existing environment for db-only calls
        if self.db_only:
            current_environments = [
                i["EnvironmentName"]
                for i in eb_client.describe_environments(ApplicationName=self.application_name)["Environments"]
            ]
            if not self.environment_name:
                print("Existing EB Environments:")
                print(sorted(current_environments))
                self.environment_name = input("Input environment name: ")
            if self.environment_name not in current_environments:
                confirmation = input(
                    f"Ignore --db-only flag and create new environment named {self.environment_name}? [y/n]"
                )
                if confirmation.lower().strip() in ["y", "yes"]:
                    self.db_only = False
                else:
                    raise Exception(f"Invalid environment name {self.environment_name}")
    
    def create_eb_config_file(self):
        config = yaml.dump(
            {
                "global": {
                    "application_name": self.application_name,
                    "default_region": self.region,
                    "profile": self.profile,
                }
            }
        )
        if not os.path.isdir(EB_GLOBAL_CONFIG_DIRECTORY):
            os.mkdir(EB_GLOBAL_CONFIG_DIRECTORY)
        with open(EB_GLOBAL_CONFIG_FILE_PATH, "w+") as config_file:
            config_file.write(config)

    def parse_config_file(self):
        with open(self.config_file_path) as config_file:
            configs = yaml.load(config_file, Loader=yaml.FullLoader)
        return configs

    def print_default_config(self):
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), DEFAULT_CONFIG_FILE_PATH)) as default_config_file:
            for line in default_config_file:
                print(line)


def main():
    SetupWrapper().setup()


if __name__ == "__main__":
    SetupWrapper().setup()
