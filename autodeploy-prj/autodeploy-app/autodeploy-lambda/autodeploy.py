import boto3
import logging
import json

# Setup simple logging for INFO
logger = logging.getLogger()
logger.setLevel(logging.INFO)

### Global variables to adjust behaviour. Change to fit your setup.
cd_app_name = "DemoApplication"
cd_dst_dg_name = "Demo-Tag-Ubuntu"
cd_dg_name = "Demo-Tag-Ubuntu-PreProd"
# Replace the following tag Key and Value for the one used in your initial Deployment Group
cd_dg_tag = {'Key': 'CodeDeploy', 'Value': 'PreProd'}

# Function to deal with paginated results. Have to generalize it. Returns a generator.
def cd_get_deployments(client, token=None, **params):
    #print token
    #for k,v in params.iteritems():
    #         print "%s = %s" % (k, v)

    results = None
    if token:
        results = client.list_deployments(nextToken=token, **params)
    else:
        results = client.list_deployments(**params)

    for i in results['deployments']:
        yield i

    if 'nextToken' in results:
        for i in cd_get_deployments(client, token=results['nextToken'], **params):
            yield i

def autodeploy_handler(event, context):
    #print ("Received event dump:")
    #print ("--------------------------------------------------------------------------------------------")
    #print (json.dumps(event, indent=2))
    #print ("--------------------------------------------------------------------------------------------")

    # Define the connections to the correct region
    ec2 = boto3.resource('ec2', region_name=event['region'])
    cd = boto3.client('codedeploy', region_name=event['region'])
       
    print "Event Region:", event['region']
    print "Event Time:", event['time']
    print "Instance ID:", event['detail']['instance-id']
    print "Instance Status:", event['detail']['state']
    
    # Obtain the EC2 object of the instance from the event
    instance = ec2.Instance(event['detail']['instance-id'])

    # Print a dict of the Tags (see https://github.com/boto/boto3/issues/264)
    print "Tags:", dict(map(lambda x: (x['Key'], x['Value']), instance.tags or []))

    # Print a dict of the filtering Tag
    print "Filter: {'%s': '%s'}" % (cd_dg_tag['Key'], cd_dg_tag['Value'])

    if instance.tags is not None:
        for t in instance.tags:
            if t['Key'] == cd_dg_tag['Key'] and t['Value'] == cd_dg_tag['Value']:
                print "Instance %s is a target for AutoDeploy!" % instance.id

    pepe = cd_get_deployments(
        cd,
        None,
        applicationName = cd_app_name,
        deploymentGroupName = cd_dst_dg_name,
        includeOnlyStatuses = ['Succeeded']
        )
    for i in pepe:
        print i
