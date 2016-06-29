import boto3
import logging
import json
import pprint
from collections import defaultdict

# Setup simple logging for INFO
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Setup PrettyPrinter
pp = pprint.PrettyPrinter(indent=2)

### Global variables to adjust behaviour. Change to fit your setup.
cd_app_name = "DemoApplication"
cd_dst_dg_name = "Demo-Tag-Ubuntu"
cd_dg_name = "Demo-Tag-Ubuntu-PreProd"
# Replace the following tag Key and Value for the one used in your initial Deployment Group
cd_dg_tag = {'Key': 'CodeDeploy', 'Value': 'PreProd'}


# Function to merge filtered dictionaries into one. Unmatched keys allowed.
# For each key specified values will become a list of values in the order
# of *args. Empty values of keys become None in the resulting list.
def dict_merger(key_filters=None, *args):
    dd = defaultdict(list)
    for d in args:
        for f in key_filters:
           dd[f].append(d.get(f))

    return dict(dd)


# Function to deal with paginated results.
def get_all_results(client_function, key_filters, **params):
    tmpResults = [client_function(**params)]

    while tmpResults[-1].get('nextToken'):
        tmpResults.append(client_function(nextToken=tmpResults[-1].get('nextToken'), **params))

    results = dict_merger(key_filters, *tmpResults)

    return results


def autodeploy_handler(event, context):
    #print ("Received event dump:")
    #print ("--------------------------------------------------------------------------------------------")
    #print (json.dumps(event, indent=2))
    #print ("--------------------------------------------------------------------------------------------")

    # Define the connections to the correct region
    ec2 = boto3.resource('ec2', region_name=event['region'])
    ec2_client = boto3.client('ec2', region_name=event['region'])
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

    deployments = get_all_results(
        cd.list_deployments,
        ['deployments'],
        applicationName = cd_app_name,
        deploymentGroupName = cd_dst_dg_name,
        includeOnlyStatuses = ['Succeeded']
        )
    # Flatten the resulting list
    deployments = [item for sublist in deployments['deployments'] for item in sublist]
    pp.pprint(deployments)

    #print "----------> instances results below:"
    #instances = get_all_results(
    #    ec2_client.describe_instances,
    #    ['Reservations']
    #    )
    #pp.pprint(instances)
