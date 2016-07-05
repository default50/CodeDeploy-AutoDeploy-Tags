import boto3
import logging
import json
import pprint
import jmespath
from itertools import izip_longest

# Setup simple logging for INFO
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Setup PrettyPrinter
pp = pprint.PrettyPrinter(indent=2)

# Global variables to adjust behaviour. Change to fit your setup.
cd_app_name = "DemoApplication"
cd_dst_dg_name = "Demo-Tag-Ubuntu"
cd_dg_name = "Demo-Tag-Ubuntu-PreProd"
# Replace the following tag Key and Value for the one used in your initial Deployment Group
cd_dg_tag = {'Key': 'CodeDeploy', 'Value': 'PreProd'}


def autodeploy_handler(event, context):
    # Define the connections to the correct region
    ec2 = boto3.resource('ec2', region_name=event['region'])
    cd = boto3.client('codedeploy', region_name=event['region'])
       
    print "Event Region: {0}".format(event['region'])
    print "Event Time: {0}".format(event['time'])
    print "Instance ID: {0}".format(event['detail']['instance-id'])
    print "Instance Status: {0}".format(event['detail']['state'])
    
    # Obtain the EC2 object of the instance from the event
    instance = ec2.Instance(event['detail']['instance-id'])

    # Print a dict of the Tags (see https://github.com/boto/boto3/issues/264)
    print "Tags: {0}".format(dict(map(lambda x: (x['Key'], x['Value']), instance.tags or [])))

    # Print a dict of the filtering Tag
    print "Filter: {{'{0}': '{1}'}}".format(cd_dg_tag['Key'], cd_dg_tag['Value'])

    if instance.tags is not None:
        for t in instance.tags:
            if t['Key'] == cd_dg_tag['Key'] and t['Value'] == cd_dg_tag['Value']:
                print "Instance {0} is a target for AutoDeploy!".format(instance.id)
 
    # Get latest successful Revision from the destination Deployment Group
    revision = jmespath.search(
        'deploymentGroupInfo.{revision:targetRevision}',
        cd.get_deployment_group(
            applicationName = cd_app_name,
            deploymentGroupName = cd_dst_dg_name,
            )
        )

    # Create Deployment for the inital Deployment Group 
    resp = cd.create_deployment(
        applicationName = cd_app_name,
        deploymentGroupName = cd_dg_name,
        **revision
        )
    pp.pprint(resp)
