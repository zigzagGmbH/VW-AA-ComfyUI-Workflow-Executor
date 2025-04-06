import asyncio
import json
import websockets
import requests
import os
import sys
import signal

# Global variables to track state
current_prompt_id = None
server = "127.0.0.1"
port = 8000

def cancel_workflow(prompt_id):
    """Cancel workflows using the global interrupt endpoint"""
    try:
        url = f"http://{server}:{port}/interrupt"
        print(f"Interrupting all workflows (including prompt ID: {prompt_id})")
        print("WARNING: This will stop ALL running workflows in ComfyUI, not just this one.")
        response = requests.post(url)
        
        if response.status_code == 200:
            print("Interrupt request sent successfully.")
            return True
        else:
            print(f"Failed to interrupt workflows. Status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"Error sending interrupt request: {e}")
        return False


def signal_handler(sig, frame):
    """Handle Ctrl+C and other termination signals"""
    print("\nReceived termination signal. Cancelling workflow and exiting...")
    
    # Cancel the current workflow if there is one
    if current_prompt_id:
        cancel_workflow(current_prompt_id)
    
    print("Exiting gracefully.")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill command

def get_user_confirmation():
    """Get synchronous user confirmation before starting workflow"""
    print("\n=== Workflow Summary ===")
    print("You are about to execute a ComfyUI workflow which may use significant GPU resources.")
    print("This will generate an image based on the workflow in the specified JSON file.")
    
    while True:
        response = input("\nDo you want to proceed with this workflow? (y/n): ")
        if response.lower() in ["n", "no", "nope"]:
            return False
        elif response.lower() in ["y", "yes", "yeah", "yep"]:
            return True
        else:
            print("Please enter 'y' or 'n'.")

async def run_workflow_and_monitor(server_addr="127.0.0.1", port_num=8000, workflow_file="workflow_api.json"):
    global current_prompt_id, server, port
    server = server_addr
    port = port_num
    
    # Check if workflow file exists
    if not os.path.exists(workflow_file):
        print(f"Error: Workflow file '{workflow_file}' not found.")
        return
    
    # Load workflow JSON from file
    try:
        with open(workflow_file, 'r') as f:
            workflow_json = json.load(f)
        print(f"Successfully loaded workflow from {workflow_file}")
        
        # Extract some details for a better summary
        model_node = None
        sampler_node = None
        positive_prompt = None
        
        for node_id, node in workflow_json.items():
            if "class_type" in node:
                if node["class_type"] == "CheckpointLoaderSimple" and "inputs" in node and "ckpt_name" in node["inputs"]:
                    model_node = node["inputs"]["ckpt_name"]
                elif node["class_type"] == "KSampler" and "inputs" in node:
                    sampler_node = node["inputs"]
                elif node["class_type"] == "CLIPTextEncode" and "_meta" in node and "title" in node["_meta"]:
                    if "Positive" in node["_meta"]["title"] and "inputs" in node and "text" in node["inputs"]:
                        positive_prompt = node["inputs"]["text"]
        
        # Print workflow summary
        print("\n=== Workflow Details ===")
        if model_node:
            print(f"Model: {model_node}")
        if sampler_node:
            print(f"Sampler: {sampler_node.get('sampler_name', 'Unknown')}")
            print(f"Steps: {sampler_node.get('steps', 'Unknown')}")
            print(f"CFG Scale: {sampler_node.get('cfg', 'Unknown')}")
        if positive_prompt:
            # Truncate long prompts
            if len(positive_prompt) > 100:
                print(f"Prompt: {positive_prompt[:100]}...")
            else:
                print(f"Prompt: {positive_prompt}")
                
    except json.JSONDecodeError:
        print(f"Error: The file {workflow_file} contains invalid JSON.")
        return
    except Exception as e:
        print(f"Error loading workflow file: {e}")
        return
    
    # Get user confirmation BEFORE connecting to WebSocket or submitting the workflow
    if not get_user_confirmation():
        print("User chose not to proceed. Exiting without submitting workflow.")
        return
    
    print("\nUser confirmed. Proceeding with workflow execution...")
    
    # Connect to WebSocket first
    ws_url = f"ws://{server}:{port}/ws"
    print(f"Connecting to WebSocket at {ws_url}...")
    
    async with websockets.connect(ws_url) as ws:
        # Receive initial status message to get session ID
        initial_msg = await ws.recv()
        initial_data = json.loads(initial_msg)
        sid = initial_data.get("data", {}).get("sid")
        
        if not sid:
            print("Failed to get session ID, using 'default_client' instead")
            sid = "default_client"
        else:
            print(f"Got session ID: {sid}")
            
        # Use this session ID as client_id for the HTTP request
        api_url = f"http://{server}:{port}/prompt"
        print(f"Submitting workflow to {api_url} with client_id: {sid}")
        
        # Submit the workflow with the session ID as client_id
        response = requests.post(
            api_url,
            json={"prompt": workflow_json, "client_id": sid}
        )
        
        if response.status_code != 200:
            print(f"Error submitting workflow: {response.status_code}")
            print(response.text)
            return
            
        result = response.json()
        prompt_id = result.get("prompt_id")
        current_prompt_id = prompt_id  # Store globally for signal handler
        print(f"Workflow submitted successfully. Prompt ID: {prompt_id}")
        
        # Subscribe to this prompt
        subscribe_msg = {
            "op": "subscribe_to_prompt", 
            "data": {"prompt_id": prompt_id}
        }
        await ws.send(json.dumps(subscribe_msg))
        print(f"Subscribed to prompt: {prompt_id}")
        
        # Monitor for events
        print("\nWaiting for execution events...")
        
        # Track execution to know when it's truly complete
        execution_complete = False
        
        try:
            # Keep receiving messages until execution completes
            while not execution_complete:
                try:
                    message = await ws.recv()
                    msg_data = json.loads(message)
                    msg_type = msg_data.get("type")
                    
                    if msg_type != "status":
                        print(f"EVENT: {msg_type}")
                        
                        # Progress updates deserve more detail
                        if msg_type == "progress":
                            value = msg_data.get("data", {}).get("value", 0)
                            max_val = msg_data.get("data", {}).get("max", 100)
                            percent = int((value / max_val) * 100)
                            print(f"  Progress: {value}/{max_val} ({percent}%)")
                        # Executing node updates
                        elif msg_type == "executing":
                            node = msg_data.get("data", {}).get("node")
                            # Build node titles dictionary from workflow JSON
                            titles = {}
                            for node_id, node_data in workflow_json.items():
                                if "_meta" in node_data and "title" in node_data["_meta"]:
                                    titles[node_id] = node_data["_meta"]["title"]
                            
                            node_title = titles.get(node, f"Node {node}")
                            print(f"  Executing: {node_title}")
                                
                        # Check for completion events
                        elif msg_type in ["execution_success", "execution_complete"]:
                            execution_complete = True
                            print("Workflow execution completed successfully!")
                            
                            # Give a short delay to capture any trailing messages
                            await asyncio.sleep(2)
                            break
                            
                except Exception as e:
                    print(f"Error receiving message: {e}")
                    break
            
            print("All events processed. Check the output folder for your generated image.")
            # Clear the prompt ID since execution is complete
            current_prompt_id = None
                
        except Exception as e:
            print(f"Error monitoring events: {e}")
            
            # If we encounter an error, attempt to cancel the workflow
            if current_prompt_id:
                cancel_workflow(current_prompt_id)

# Main execution
if __name__ == "__main__":
    print("Starting ComfyUI workflow executor (Press Ctrl+C to cancel at any time)")
    try:
        # Try to run the workflow from the file
        asyncio.run(run_workflow_and_monitor())
    except KeyboardInterrupt:
        # This should be caught by the signal handler, but just in case
        print("\nKeyboard interrupt detected.")
        if current_prompt_id:
            cancel_workflow(current_prompt_id)
    finally:
        print("Script execution complete.")
