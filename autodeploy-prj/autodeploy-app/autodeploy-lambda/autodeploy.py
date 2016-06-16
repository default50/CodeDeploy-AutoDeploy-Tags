import boto3
import logging
import json

#setup simple logging for INFO
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def autodeploy_handler(event, context):
    #print ("Received event dump:")
    #print ("--------------------------------------------------------------------------------------------")
    #print (json.dumps(event, indent=2))
    #print ("--------------------------------------------------------------------------------------------")
    
    # Replace the following tag Key and Value for the one used in your initial Deployment Group
    dg_tag = {'Key': 'CodeDeploy', 'Value': 'PreProd'}

    # Define the connection to the correct region
    ec2 = boto3.resource('ec2', region_name=event['region'])
   
    print "Event Region:", event['region']
    print "Event Time:", event['time']
    print "Instance ID:", event['detail']['instance-id']
    print "Instance Status:", event['detail']['state']
    
    # Obtain the EC2 object of the instance from the event
    instance = ec2.Instance(event['detail']['instance-id'])

    # Print a dict of the Tags (see https://github.com/boto/boto3/issues/264)
    print "Tags:", dict(map(lambda x: (x['Key'], x['Value']), instance.tags or []))

    # Print a dict of the filtering Tag
    print "Filter: {'%s': '%s'}" % (dg_tag['Key'], dg_tag['Value'])

    if instance.tags is not None:
        for t in instance.tags:
            if t['Key'] == dg_tag['Key'] and t['Value'] == dg_tag['Value']:
                print "Instance %s is a target for AutoDeploy!" % instance.id
