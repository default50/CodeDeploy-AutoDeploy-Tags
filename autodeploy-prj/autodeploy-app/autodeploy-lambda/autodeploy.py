import boto3
import logging
import json
import pprint
import jmespath
from itertools import izip_longest
from random import choice
from string import ascii_uppercase, digits

# Setup simple logging for INFO
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Setup PrettyPrinter
pp = pprint.PrettyPrinter(indent=2)

# Global variables to adjust behaviour. Change to fit your setup.
cd_app_name = 'DemoApplication'
cd_dg_name = 'Demo-Tag-Ubuntu'
# Replace the following tag Key and Value for the one used in your initial Deployment Group
# ToDo: look this up automatically from the DG
cd_dg_tag = {'Key': 'Name', 'Value': 'CodeDeployDemo-Tag-Ubuntu'}


def instance_launch_handler(event, context):
    #with open('/tmp/.context', 'r') as f:
    with open('.context', 'r') as f:
        gordon_context = json.loads(f.read())

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
        if cd_dg_tag in instance.tags:
            print "Instance {0} is a target for AutoDeploy!".format(instance.id)
        else:
            print "Instance {0} didn't have any matching Tags. Doing nothing!".format(instance.id)
            return
    else:
        print "Instance {0} didn't have any Tags. Doing nothing!".format(instance.id)
        return

    # Generate random suffix ala CloudFormation for temporary Deployment Group and Tags   
    suffix = ''.join(choice(ascii_uppercase + digits) for i in range(13))

    # Get information from destination Deployment Group
    deployment_group = cd.get_deployment_group(
        applicationName = cd_app_name,
        deploymentGroupName = cd_dg_name
        )
    ###pp.pprint(deployment_group)

    # Build Revision dict from the destination Deployment Group
    revision = jmespath.search(
        'deploymentGroupInfo.{revision:targetRevision}',
        deployment_group
        )
    ###pp.pprint(revision)

    # Tag instance with unique Tag
    ec2.create_tags(
        Resources=[instance.id],
        Tags=[{'Key': 'DeploymentGroup-'+suffix, 'Value': 'True-'+suffix}]
        )

    # Create unique temporary Deployment Group targetting the instance by it's unique Tags
    resp = cd.create_deployment_group(
            applicationName = cd_app_name,
            deploymentGroupName = cd_dg_name+'-'+suffix,
            ec2TagFilters=[{
                    'Key': 'DeploymentGroup-'+suffix,
                    'Value': 'True-'+suffix,
                    'Type': 'KEY_AND_VALUE'}],
            serviceRoleArn=deployment_group['deploymentGroupInfo']['serviceRoleArn'],
            triggerConfigurations=[{
                    'triggerEvents': [
                        'DeploymentSuccess'
                    ],
                    'triggerTargetArn': gordon_context['trigger_arn'],
                    'triggerName': 'AutoDeploy'
                    }]
        )
    ###pp.pprint(resp)

    # Create Deployment for the unique Deployment Group 
    resp = cd.create_deployment(
        applicationName = cd_app_name,
        deploymentGroupName = cd_dg_name+'-'+suffix,
        **revision
        )
    ###pp.pprint(resp)

    return 'SUCCESS: Deployment triggered'

def sns_handler(event, context):

    if 'SUCCESS: AWS CodeDeploy notification setup for trigger' in jmespath.search('Records[].Sns[].Subject', event)[0]:

        print "SNS notification setup for trigger received. Message: \n" + jmespath.search('Records[].Sns[].Message', event)[0]
        return 'SUCCESS: SNS trigger configuration notification received'

    elif 'SUCCEEDED: AWS CodeDeploy' in jmespath.search('Records[].Sns[].Subject', event)[0]:

        # The CodeDeploy event result comes inside the Message of the SNS notification.
        message = json.loads(jmespath.search('Records[].Sns[].Message', event)[0])

        # Define the connections to the correct region
        # Using client for ec2 because of missing delete_tags() on the resource
        # https://github.com/boto/boto3/issues/381
        ec2 = boto3.client('ec2', region_name=message['region'])
        cd = boto3.client('codedeploy', region_name=message['region'])
    
        suffix = message['deploymentGroupName'][-13:]
    
        filters = [{'Name': 'tag:DeploymentGroup-'+suffix, 'Values': ['True-'+suffix]}]
    
        # Find instances with unique Tag
        instance = jmespath.search('Reservations[].Instances[].InstanceId', ec2.describe_instances(Filters=filters))
    
        if len(instance) is 1:
            # Delete unique Tag
            ec2.delete_tags(
                Resources=[instance[0]],
                Tags=[{'Key': 'DeploymentGroup-'+suffix, 'Value': 'True-'+suffix}]
                )
        else:
            return "FAIL: Should have one and only one instance matching {{'{0}': '{1}'}}".format(filters[0]['Name'], filters[0]['Values'][0])
    
        # Delete unique temporary Deployment Group
        cd.delete_deployment_group(
            applicationName=message['applicationName'],
            deploymentGroupName=message['deploymentGroupName']
            )
        
        return 'SUCCESS: Cleaned up temporary Deployment Group and Tags'
    
def autodeploy_handler(event, context):

    if jmespath.search('["detail-type", detail.state]', event) == [u'EC2 Instance State-change Notification', u'running']:
        print "Call instance_launch_handler"
        return instance_launch_handler(event, context)
    elif jmespath.search('Records[].EventSource[]', event)[0] == 'aws:sns':
        print "Call sns_handler"
        return sns_handler(event, context)
    else:
        print "WARNING: Unkown event received!\nDump of event:\n" + json.dumps(event, indent=2)
        return 'WARNING: Unknown event'
