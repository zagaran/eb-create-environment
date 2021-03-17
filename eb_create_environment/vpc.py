import boto3


class VPCAccessor(object):
    def __init__(self, region):
        self.region = region
    
    def get_ec2_resources(self):
        return boto3.resource("ec2", self.region)
    
    def get_vpcs(self):
        ec2_resources = self.get_ec2_resources()
        vpcs = {}
        for vpc in ec2_resources.vpcs.all():
            vpcs[vpc.id] = None
            if vpc.is_default:
                vpcs[vpc.id] = "Default"
            if vpc.tags:
                name_tags = [tag["Value"] for tag in vpc.tags if tag["Key"] == "Name"]
                if name_tags:
                    vpcs[vpc.id] = name_tags[0]
        return vpcs
    
    def get_subnets(self, vpc_id, public=True):
        ec2_resources = self.get_ec2_resources()
        vpc = ec2_resources.Vpc(vpc_id)
        subnets = {}
        for subnet in vpc.subnets.all():
            subnets[subnet.id] = subnet.availability_zone
        public_subnets = {}
        private_subnets = {}
        
        route_tables = ec2_resources.route_tables.all()
        main_route_table_public = False
        for route_table in route_tables:
            if route_table.vpc.id != vpc_id:
                continue
            is_public = self.is_route_table_public(route_table)
            for association in route_table.associations:
                if association.main:
                    main_route_table_public = is_public
                if association.subnet:
                    if is_public:
                        public_subnets[association.subnet.id] = subnets.pop(association.subnet.id)
                    else:
                        private_subnets[association.subnet.id] = subnets.pop(association.subnet.id)
        if main_route_table_public:
            public_subnets.update(subnets)
        else:
            private_subnets.update(subnets)
    
        if public:
            return public_subnets
        else:
            return private_subnets
    
    def is_route_table_public(self, route_table):
        return any(ra.get('DestinationCidrBlock') == '0.0.0.0/0' and ra.get('GatewayId') is not None for ra in route_table.routes_attribute)
