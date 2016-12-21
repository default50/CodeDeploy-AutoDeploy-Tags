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
cd_app_name = 'AutoDeploy-TestApp'
cd_dg_name = 'AutoDeploy-TestDG'
terminate_on_fail = False
# Replace the following tag Key and Value for the one used in your initial Deployment Group
# TODO: look this up automatically from the DG
cd_dg_tags = [{'Key': 'AutoDeploy', 'Value': 'Test'}]


def instance_state_handler(event, context):

    if event['detail']['state'] != 'running':
        logger.error('Unexpected instance state: \'{0}\'. Check CloudWatch Events rules.'.format(event['detail']['state']))
        return 'ERROR: Unexpected instance state: \'{0}\'. Check CloudWatch Events rules.'.format(event['detail']['state'])
    else:
        logger.info('Event from region {0}. Instance {1} is now in \'{2}\' state.'.format(event['region'], event['detail']['instance-id'], event['detail']['state']))
    
    # Define the connections to the correct region
    ec2 = boto3.client('ec2', region_name=event['region'])
    cd = boto3.client('codedeploy', region_name=event['region'])
   
    # Obtain the EC2 object of the instance from the event
    instance = jmespath.search('Reservations[].Instances[] | [0]', ec2.describe_instances(InstanceIds=[event['detail']['instance-id']]))

    # Log a dict of the filtering Tags (see https://github.com/boto/boto3/issues/264)
    logger.debug('Filtering instances with these tags: {0}'.format(dict(map(lambda x: (x['Key'], x['Value']), cd_dg_tags))))

    # Log a dict of the Tags (see https://github.com/boto/boto3/issues/264)
    logger.debug("Instance has this tags: {0}".format(dict(map(lambda x: (x['Key'], x['Value']), instance.get('Tags', [])))))

    # TODO: Review this logic. Maybe control if it has the "special" random tag and use it to abort/detect parallel deployments
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
    # TODO:
    # - Maybe use the "Description" of the revision to store the marker about the deployment being done by AutoDeploy.
    # - If there's no previous revision fall back to a predefined one.
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
    response = cd.update_deployment_group(
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
    response = cd.update_deployment_group(
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


def deploy_state_handler(event, context):

    if event['detail']['state'] != 'FAILURE':
        logger.error('Unexpected deployment to instance state: \'{0}\'. Check CloudWatch Events rules.'.format(event['detail']['state']))
        return 'ERROR: Unexpected deployment instance state: \'{0}\'. Check CloudWatch Events rules.'.format(event['detail']['state'])
    else:
# TODO: find out if the deployment failed was triggered by AutoDeploy to continue with termination, if not abort
        logger.info('Event from region {0}. Deployment {1} to instance {2} is now in \'{3}\' state.'.format(event['region'], event['detail']['deploymentId'], event['detail']['instanceId'], event['detail']['state']))

    # Define the connections to the correct region
    ec2 = boto3.client('ec2', region_name=event['region'])

    if terminate_on_fail is True:
        response = ec2.terminate_instances(
            DryRun=True,
            InstanceIds=[event['detail']['instanceId']]
        )
    else:
        logger.warning('\'terminate_on_failure\' flag is not enabled, skipping termination of instance {}'.format(event['detail']['instanceId']))
        return 'WARNING: \'terminate_on_failure\' flag is not enabled, skipping termination of instance {}'.format(event['detail']['instanceId'])


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

    event_pattern = jmespath.search('["detail-type", source]', event)
    if event_pattern == [u'EC2 Instance State-change Notification', u'aws.ec2']:
        logger.info('EC2 instance state-change notification received.')
        return instance_state_handler(event, context)
    elif event_pattern == [u'CodeDeploy Instance State-change Notification', u'aws.codedeploy']:
        logger.info('CodeDeploy instance state-change notification received.')
        return deploy_state_handler(event, context)
    else:
        logger.warning('Unkown event received. Dump of event:\n{}'.format(json.dumps(event, indent=2)))
        return 'WARNING: Unknown event received.'
