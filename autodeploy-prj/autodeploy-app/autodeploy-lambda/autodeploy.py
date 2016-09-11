from __future__ import print_function

import boto3
import botocore
import logging
import json
import jmespath
from random import choice
from string import ascii_uppercase, digits
import time

# Setup simple logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Global variables to adjust behaviour. Change to fit your setup.
cd_app_name = 'DemoApplication'
cd_dg_name = 'Demo-Tag-Ubuntu'
# Replace the following tag Key and Value for the one used in your initial Deployment Group
# ToDo: look this up automatically from the DG
cd_dg_tags = [{'Key': 'Name', 'Value': 'CodeDeployDemo-Tag-Ubuntu'}]


def instance_state_handler(event, context):

    logger.info('Event from region {0}. Instance {1} is now in \'{2}\' state.'.format(event['region'], event['detail']['instance-id'], event['detail']['state']))
    
    # Define the connections to the correct region
    ec2 = boto3.client('ec2', region_name=event['region'])
    cd = boto3.client('codedeploy', region_name=event['region'])
   
    # Obtain the EC2 object of the instance from the event
    instance = jmespath.search('Reservations[].Instances[] | [0]', ec2.describe_instances(InstanceIds=[event['detail']['instance-id']]))

    # Log a dict of the filtering Tags (see https://github.com/boto/boto3/issues/264)
    logger.debug("Filtering instances with these tags: {0}".format(dict(map(lambda x: (x['Key'], x['Value']), cd_dg_tags))))

    # Log a dict of the Tags (see https://github.com/boto/boto3/issues/264)
    logger.debug("Instance has this tags: {0}".format(dict(map(lambda x: (x['Key'], x['Value']), instance.get('Tags', [])))))

    # Check if the instance has at least one of the tags in the filter
    if len([tag for tag in cd_dg_tags if tag in instance.get('Tags', [])]) > 0:
        logger.info('Instance {0} is a target for AutoDeploy!'.format(instance['InstanceId']))
    else:
        logger.warning('Couldn\'t find any matching Tags for instance {0}. Skipping event.'.format(instance['InstanceId']))
        return 'WARNING: Couldn\'t find any matching Tags for instance {0}. Skipping event.'.format(instance['InstanceId'])

    # Generate random suffix ala CloudFormation for temporary Deployment Group and Tags   
    suffix = ''.join(choice(ascii_uppercase + digits) for i in range(13))
    logger.info('Using AutoDeploy-{0} as a temporary identifier.'.format(suffix))

    # Get information from Deployment Group
    deployment_group = cd.get_deployment_group(
        applicationName = cd_app_name,
        deploymentGroupName = cd_dg_name
        )
    logger.debug(deployment_group)

    # Save the original targets
    orig_targets = jmespath.search(
        'deploymentGroupInfo.{ec2TagFilters:ec2TagFilters,onPremisesInstanceTagFilters:onPremisesInstanceTagFilters,autoScalingGroups:autoScalingGroups[*].name}',
        deployment_group
        )

    # Build Revision dict from the Deployment Group
    revision = jmespath.search(
        'deploymentGroupInfo.{revision:targetRevision}',
        deployment_group
        )

    # Tag instance with unique Tag
    ec2.create_tags(
        Resources=[instance['InstanceId']],
        Tags=[{'Key': 'AutoDeploy-'+suffix, 'Value': 'True'}]
        )

    # Make Deployment Group target the unique instance
    resp = cd.update_deployment_group(
            applicationName = cd_app_name,
            currentDeploymentGroupName = cd_dg_name,
            autoScalingGroups=[],
            onPremisesInstanceTagFilters=[],
            ec2TagFilters=[{
                    'Key': 'AutoDeploy-'+suffix,
                    'Value': 'True',
                    'Type': 'KEY_AND_VALUE'}]
            )
   
    # Wait for instance to have appropriate tags
    instance = jmespath.search('Reservations[].Instances[] | [0]', ec2.describe_instances(InstanceIds=[event['detail']['instance-id']]))
    while {'Key': 'AutoDeploy-'+suffix, 'Value': 'True'} not in instance['Tags']:
        logger.debug('Unique tag still not visible on instance. Sleeping and retrying.')
        time.sleep(.500)
        instance = jmespath.search('Reservations[].Instances[] | [0]', ec2.describe_instances(InstanceIds=[event['detail']['instance-id']]))

    # Create Deployment (unless there's a running one)
    deployment = {}
    try:
        deployment = cd.create_deployment(
            applicationName = cd_app_name,
            deploymentGroupName = cd_dg_name,
            **revision
            )

        # Wait for Deployment not to be in 'Created' state
        while (cd.get_deployment(deploymentId=deployment['deploymentId']).get('deploymentInfo', {}).get('status', {})) == 'Created':
            time.sleep(.500)

    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'DeploymentLimitExceededException':
            logger.error(e.response['Error']['Message'])
        else:
            raise(e)

    # Restore Deployment Group original targets
    resp = cd.update_deployment_group(
        applicationName = cd_app_name,
        currentDeploymentGroupName = cd_dg_name,
        **orig_targets
        )

    # Delete unique Tag
    ec2.delete_tags(
        Resources=[instance['InstanceId']],
        Tags=[{'Key': 'AutoDeploy-'+suffix, 'Value': 'True'}]
        )

    if deployment.get('deploymentId') is not None:
        logger.info('SUCCESS: Deployment {0} triggered'.format(deployment['deploymentId']))
        return 'SUCCESS: Deployment {0} triggered'.format(deployment['deploymentId'])
    else:
        return 'ERROR: {}'.format(e.response['Error']['Message'])


def sns_handler(event, context):

    # Process the notification received when the Trigger for the Deployment Group is created
    if 'SUCCESS: AWS CodeDeploy notification setup for trigger' in jmespath.search('Records[].Sns[].Subject', event)[0]:

        logger.info('SNS notification setup for trigger received. Message: \n{}'.format(jmespath.search('Records[].Sns[].Message | [0]', event)))
        return 'SUCCESS: SNS trigger configuration notification received'

    # Process the notification received when the deployment is SUCCEEDED
    elif 'SUCCEEDED: AWS CodeDeploy' in jmespath.search('Records[].Sns[].Subject | [0]', event):

        # The CodeDeploy event result comes inside the Message of the SNS notification.
        message = json.loads(jmespath.search('Records[].Sns[].Message | [0]', event))

        logger.warning('WARNING: Successful deployments notifications are unhandled. Message:\n{}'.format(json.dumps(message, indent=2)))
        return 'WARNING: Successful deployments notifications are unhandled.'

    # Process the notification received when the deployment is FAILED
    elif 'FAILED: AWS CodeDeploy' in jmespath.search('Records[].Sns[].Subject | [0]', event):

        # The CodeDeploy event result comes inside the Message of the SNS notification.
        message = json.loads(jmespath.search('Records[].Sns[].Message | [0]', event))

        ######## Terminate instance if failed deployment ala ASG
        ###error_info = json.loads(message['errorInformation'])
        ###error_info['ErrorCode']

        logger.info('FAILED')
        return 'FAILED'

    # Unhandled SNS notification received
    else:
        logger.warning('WARNING: Unhandled SNS notification received. Dump of event:\n{}'.format(json.dumps(event, indent=2)))
        return 'WARNING: Unhandled SNS notification received.'
    
def autodeploy_handler(event, context):

    # Detect if we are being run locally through gordon and output logger to stdout
    if context.function_name == 'autodeploy-lambda':
        import sys
        stdout = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(fmt='[%(levelname)s] %(asctime)s.%(msecs)03d %(message)s', datefmt='%Y-%m-%d,%H:%M:%S')
        stdout.setFormatter(formatter)
        logger.addHandler(stdout)
        logger.setLevel(logging.INFO)

    logger.info('AutoDeploy function invoked for Application \'{0}\' and Deployment Group \'{1}\'.'.format(cd_app_name, cd_dg_name))
    
    if jmespath.search('["detail-type", detail.state]', event) == [u'EC2 Instance State-change Notification', u'running']:
        logger.info('Instance state-change notification received.')
        return instance_state_handler(event, context)
    elif jmespath.search('Records[].EventSource[]', event)[0] == 'aws:sns':
        logger.info('SNS notification received.')
        return sns_handler(event, context)
    else:
        logger.warning('Unkown event received. Dump of event:\n{}'.format(json.dumps(event, indent=2)))
        return 'WARNING: Unknown event received.'
