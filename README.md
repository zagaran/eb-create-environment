# eb-environment-creation

Tired of byzantine EB environment and RDS instance creation workflows? Use this tool to set up Elastic Beanstalk 
environments and linked RDS instances simply, without having to rely on the AWS interface. The tool ships with sensible
defaults, which may be overridden if desired.

# Instalation
`pip install eb-create-environment`

# Usage
```
usage: eb-create-environment [-h] [-c CONFIG] [-a APPLICATION_NAME]
                             [-e ENVIRONMENT_NAME] [-p PROFILE] [-r REGION]
                             [--db-only]

Set up linked EB and RDS instances

optional arguments:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        Specify a custom config file
  -a APPLICATION_NAME, --application_name APPLICATION_NAME
                        Elastic Beanstalk application name
  -e ENVIRONMENT_NAME, --environment_name ENVIRONMENT_NAME
                        Elastic Beanstalk environment name
  -p PROFILE, --profile PROFILE
                        Specify an AWS profile from your credential file
  -r REGION, --region REGION
                        Specify an AWS region region
  --db-only             Skip setup of application and environment. Requires
                        application and environment to exist already.
  --print-default-config
                        Print default config and exit

```
* Override default configs by createing a custom config yaml file and specify its path using the `--config` option (see [Customizing the config file](#customizing-the-config-file))
* Print defaults with the `--print-default-config` option
* Elastic beanstalk configuration (application name, authentication profile name, default region) are read from the 
  `.elasticbeanstalk/config.yml` file if it exists. Otherwise, the user will be prompted for these values and the 
  config file will be created.
* If arguments are missing the user will be prompted for required inputs.
* If the desired environment already exists, skip environment setup and create an associated RDS instance using the 
  `--db-only` option.
* If `--db-only` is not selected, `eb-create-environment` will create an EB environment with the specified parameters,
  create a database in the same VPC, create the necessary security groups, and set the `DATABASE_URL` environment
  variable on the EB environment.

## Customizing the config file

To get a new config file, `eb-create-environment --print-default-config > .elasticbeanstalk/ENVIRONMENT_NAME.yml`

The default config file is [eb_create_environment/default_config.yml](eb_create_environment/default_config.yml).  `eb-create-environment` will use this file as it's config file if no `--config` option is passed.

You can override this default by copying this file, modifying its values, and specifying its path using the `--config` option.  It is recommended that you include these files in your codebase in a directory called `.elasticbeanstalk`.

Params under the `ElasticBeanstalk` top-level key are used in [eb_create_environment/eb_setup.py](eb_create_environment/eb_setup.py) while params under the `RDS` top-level key are used in [eb_create_environment/database.py](eb_create_environment/database.py).
