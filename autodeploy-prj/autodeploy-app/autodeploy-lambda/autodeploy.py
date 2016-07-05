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


# Function to deal with paginated results.
def get_all_results(client_function, jmes_query=None, flatten=False, **params):
    results = list()
    tmpResults = [client_function(**params)]

    while tmpResults[-1].get('nextToken'):
        tmpResults.append(client_function(nextToken=tmpResults[-1].get('nextToken'), **params))

    if jmes_query:
        for r in tmpResults:
            results.append(jmespath.search(jmes_query, r))
        if flatten:
            return [item for sublist in results for item in sublist]
        else:
            return results
    else:
        if flatten:
            return [item for sublist in tmpResults for item in sublist]
        else:
            return tmpResults


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
 
    # Get all successful deployments from the destination Deployment Group
    deployments = get_all_results(
        cd.list_deployments,
        'deployments',
        flatten=True,
        applicationName = cd_app_name,
        deploymentGroupName = cd_dst_dg_name,
        includeOnlyStatuses = ['Succeeded']
        )

    # Get details about the previously found deployments, in batches (max 100) 
    deployments_info = list()
    chunk_size = [iter(deployments)] * 100 # batch_get_deployments has a max of 100 IDs as input

    for chunk in izip_longest(*chunk_size):
        chunk = filter(lambda x: x!=None, chunk) # Remove None fillings from list
        deployments_info.extend(get_all_results(
            cd.batch_get_deployments,
            'deploymentsInfo[].[deploymentId,createTime]',
            flatten=True,
            deploymentIds=chunk)
            )
   
    deployments_info.sort(key=lambda x: x[1])
    latest_deployment = deployments_info[-1][0]

    deployment_template = jmespath.search(
        'deploymentInfo.{applicationName:applicationName,deploymentGroupName:deploymentGroupName,revision:revision,deploymentConfigName:deploymentConfigName}',
        cd.get_deployment(deploymentId=latest_deployment)
        )
    deployment_template['deploymentGroupName'] = cd_dg_name # Overwrite the Deployment Group name
    deployment_template['description'] = "Created from Lambda"

    resp = cd.create_deployment(**deployment_template)
    pp.pprint(resp)
