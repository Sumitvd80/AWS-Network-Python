#!/bin/bash

# Define your EC2 instance ID and EBS volume ID here
INSTANCE_ID="i-0d6561h3"
VOLUME_ID="vol-062ea60hhg19"
REGION="us-east-1"


# Get the instance tags in text format
INSTANCE_TAGS_TEXT=$(aws ec2 describe-tags --region "$REGION" --filters "Name=resource-id,Values=$INSTANCE_ID" --query 'Tags[*].[Key,Value]' --output text)

# Check if any tags are found
if [ -z "$INSTANCE_TAGS_TEXT" ]; then
    echo "No tags found on instance $INSTANCE_ID."
    exit 1
fi

# Convert tags into AWS CLI format
TAGS_ARRAY=()
while IFS=$'\t' read -r KEY VALUE; do
    TAGS_ARRAY+=("Key=$KEY,Value=$VALUE")
done <<< "$INSTANCE_TAGS_TEXT"

# Apply tags to the volume
aws ec2 create-tags --region "$REGION" --resources "$VOLUME_ID" --tags "${TAGS_ARRAY[@]}"

echo "Tags copied from instance $INSTANCE_ID to volume $VOLUME_ID."


# Let's break down this Bash script step by step:

# #!/bin/bash: This is the shebang line. It tells the operating system that this script should be executed with the Bash interpreter.

# # Define your EC2 instance ID and EBS volume ID here: This is a comment explaining the purpose of the following lines.

# INSTANCE_ID="i-0591f473ceb": This line defines a variable named INSTANCE_ID and assigns it the value of your EC2 instance ID. You need to replace this with your actual EC2 instance ID.

# VOLUME_ID="vol-027d75657a5": This line defines a variable named VOLUME_ID and assigns it the value of your EBS volume ID. You need to replace this with your actual EBS volume ID.

# REGION="us-east-1": This line defines a variable named REGION and assigns it the AWS region where your EC2 instance and EBS volume are located. You need to replace this with your actual AWS region.

# # Get the instance tags in text format: Another comment explaining the next command.

# INSTANCE_TAGS_TEXT=$(aws ec2 describe-tags --region "$REGION" --filters "Name=resource-id,Values=$INSTANCE_ID" --query 'Tags[*].[Key,Value]' --output text):

# This is the core command to retrieve the tags associated with your EC2 instance.
# aws ec2 describe-tags: This is the AWS CLI command to describe tags for EC2 resources.
# --region "$REGION": Specifies the AWS region to query, using the value stored in the REGION variable.
# --filters "Name=resource-id,Values=$INSTANCE_ID": This filters the tags to only include those associated with the EC2 instance specified by the INSTANCE_ID variable.
# --query 'Tags[*].[Key,Value]': This is a JMESPath query that tells the AWS CLI to extract the Key and Value of each tag from the output. The [*] selects all elements in the Tags array, and .[Key,Value] selects the Key and Value fields from each element.
# --output text: This tells the AWS CLI to format the output as tab-separated text. Each line will contain a tag's key and its value separated by a tab.
# The entire command is enclosed in $(...), which is command substitution. The output of this command will be captured and stored in the INSTANCE_TAGS_TEXT variable.
# # Check if any tags are found: A comment explaining the next conditional block.

# if [ -z "$INSTANCE_TAGS_TEXT" ]; then:

# This starts an if statement.
# [ -z "$INSTANCE_TAGS_TEXT" ]: This is a conditional expression that checks if the INSTANCE_TAGS_TEXT variable is empty (has a length of zero).
# If the variable is empty, it means no tags were found on the specified EC2 instance.
# echo "No tags found on instance $INSTANCE_ID.": If no tags are found, this line prints a message to the console.

# exit 1: If no tags are found, this line exits the script with a status code of 1, indicating an error.

# fi: This ends the if statement.

# # Convert tags into AWS CLI format: A comment explaining the next section.

# TAGS_ARRAY=(): This initializes an empty array named TAGS_ARRAY. This array will store the tags in the format required by the aws ec2 create-tags command (Key=value).

# while IFS=$'\t' read -r KEY VALUE; do:

# This starts a while loop that reads the contents of the INSTANCE_TAGS_TEXT variable line by line.
# IFS=$'\t': This sets the Internal Field Separator (IFS) to a tab character. This is crucial because the aws ec2 describe-tags --output text command separates the key and value with a tab.
# read -r KEY VALUE: This reads each line of the input and splits it into two variables, KEY and VALUE, using the tab as the delimiter. The -r option prevents backslash escapes from being interpreted.
# done <<< "$INSTANCE_TAGS_TEXT": This uses a "here string" to feed the content of the INSTANCE_TAGS_TEXT variable as input to the while loop.
# TAGS_ARRAY+=("Key=$KEY,Value=$VALUE"):

# Inside the loop, this line constructs a string in the format Key=value using the extracted KEY and VALUE variables.
# TAGS_ARRAY+=("..."): This appends the newly created string as a new element to the TAGS_ARRAY.
# # Apply tags to the volume: A comment explaining the next command.

# aws ec2 create-tags --region "$REGION" --resources "$VOLUME_ID" --tags "${TAGS_ARRAY[@]}":

# This is the AWS CLI command to apply tags to the EBS volume.
# aws ec2 create-tags: The command to create tags for EC2 resources.
# --region "$REGION": Specifies the AWS region, using the value from the REGION variable.
# --resources "$VOLUME_ID": Specifies the ID of the EBS volume to apply the tags to, using the value from the VOLUME_ID variable.
# --tags "${TAGS_ARRAY[@]}": This is the crucial part. It passes the tags stored in the TAGS_ARRAY to the command.
# "${TAGS_ARRAY[@]}" expands the array into a space-separated list of strings, where each string is in the format Key=value. This is the format expected by the aws ec2 create-tags command for the --tags parameter.
# echo "Tags copied from instance $INSTANCE_ID to volume $VOLUME_ID.": This line prints a confirmation message to the console.

# In summary, this script does the following:

# Defines variables for the EC2 instance ID, EBS volume ID, and AWS region.
# Retrieves the tags associated with the specified EC2 instance using the AWS CLI and stores them in a tab-separated text format.
# Checks if any tags were found on the instance. If not, it exits.
# Parses the tab-separated text output, extracting the key and value of each tag.
# Constructs an array of tags in the format Key=value.
# Applies the tags from the array to the specified EBS volume using the AWS CLI.
# Prints a confirmation message.
