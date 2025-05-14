import asyncio
import json
import websockets
import requests
import os
import sys
import signal
import colorama
from colorama import Fore, Style
from aiohttp import web


# Initialize colorama for cross-platform colored terminal output
colorama.init()


# Global variables to track state
current_prompt_id = None
server = "127.0.0.1"
port = 8188
curr_workflow = "just_open_pause_api.json"
MIDDLEWARE_HTTP_PORT = 8189  # Port for our middle ware HTTP server


# Global variables to track state
# RUN_MODE = "server"  # Options: "execute_and_exit" or "server"
# RUN_MODE = "single_shot"  # Options: "single_shot" or "continuous"
RUN_MODE = "continuous"  # Options: "single_shot" or "continuous"


async def handle_health_check(request):
    """Simple health check endpoint"""
    return web.Response(text="ComfyUI Workflow Runner is running")


async def start_minimal_http_server():
    """Start a minimal HTTP server"""
    app = web.Application()

    # Add routes
    app.router.add_get("/health", handle_health_check)

    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, server, MIDDLEWARE_HTTP_PORT)

    print(f"{Fore.LIGHTYELLOW_EX}Starting HTTP server on:{Fore.LIGHTBLACK_EX} http://{server}:{MIDDLEWARE_HTTP_PORT} {Style.RESET_ALL}")
    await site.start()

    return runner


def test_comfyui_connection(server_addr, port_num):
    """Test connectivity to ComfyUI server"""

    try:
        url = f"http://{server_addr}:{port_num}/system_stats"
        print(
            f"{Fore.LIGHTYELLOW_EX}Testing connectivity to ComfyUI at{Fore.LIGHTBLACK_EX} {url} {Style.RESET_ALL}"
        )

        response = requests.get(url)
        if response.status_code == 200:
            print(f"{Fore.LIGHTGREEN_EX}ComfyUI connection successful{Style.RESET_ALL}")
            # [OPTIONAL]
            # Print some res values
            return True
        else:
            print(
                f"{Fore.LIGHTRED_EX}ComfyUI connection failed: {Fore.LIGHTBLACK_EX}{response.status_code}{Style.RESET_ALL}"
            )
            return False
    except Exception as e:
        print(
            f"{Fore.LIGHTRED_EX}Error connecting to ComfyUI: \n{Fore.LIGHTBLACK_EX}{e}{Style.RESET_ALL}"
        )
        return False


def cancel_workflow(prompt_id):
    """Cancel workflows using the global interrupt endpoint"""
    try:
        url = f"http://{server}:{port}/interrupt"
        print(f"Interrupting all workflows (including prompt ID: {prompt_id})")
        print(
            "WARNING: This will stop ALL running workflows in ComfyUI, not just this one."
        )
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
    print(
        "You are about to execute a ComfyUI workflow which may use significant GPU resources."
    )
    print(
        "This will generate an image based on the workflow in the specified JSON file."
    )

    while True:
        response = input("\nDo you want to proceed with this workflow? (y/n): ")
        if response.lower() in ["n", "no", "nope"]:
            return False
        elif response.lower() in ["y", "yes", "yeah", "yep"]:
            return True
        else:
            print("Please enter 'y' or 'n'.")


def load_workflow_from_file(
    workflow_file="txt_to_img_hello_world_sdxl_api_comfy_cli_ver.json",
):
    """Load workflow JSON from file without executing it"""
    # Check if workflow file exists
    if not os.path.exists(workflow_file):
        print(
            f"{Fore.LIGHTRED_EX}Error: Workflow file '{workflow_file}' not found.{Style.RESET_ALL}"
        )
        return None

    # Load workflow JSON from file
    try:
        with open(workflow_file, "r") as f:
            workflow_json = json.load(f)

        print(
            f"{Fore.LIGHTGREEN_EX}Workflow loaded: {Fore.BLACK}{workflow_file}{Style.RESET_ALL}"
        )

        # [OPTIONAL]
        # # Extract some details for a better summary
        # model_node = None
        # sampler_node = None
        # positive_prompt = None

        # for node_id, node in workflow_json.items():
        #     if "class_type" in node:
        #         if node["class_type"] == "CheckpointLoaderSimple" and "inputs" in node and "ckpt_name" in node["inputs"]:
        #             model_node = node["inputs"]["ckpt_name"]
        #         elif node["class_type"] == "KSampler" and "inputs" in node:
        #             sampler_node = node["inputs"]
        #         elif node["class_type"] == "CLIPTextEncode" and "_meta" in node and "title" in node["_meta"]:
        #             if "Positive" in node["_meta"]["title"] and "inputs" in node and "text" in node["inputs"]:
        #                 positive_prompt = node["inputs"]["text"]
        # # Print workflow summary
        # print("\n=== Workflow Details ===")
        # if model_node:
        #     print(f"Model: {model_node}")
        # if sampler_node:
        #     print(f"Sampler: {sampler_node.get('sampler_name', 'Unknown')}")
        #     print(f"Steps: {sampler_node.get('steps', 'Unknown')}")
        #     print(f"CFG Scale: {sampler_node.get('cfg', 'Unknown')}")
        # if positive_prompt:
        #     # Truncate long prompts
        #     if len(positive_prompt) > 100:
        #         print(f"Prompt: {positive_prompt[:100]}...")
        #     else:
        #         print(f"Prompt: {positive_prompt}")
        return workflow_json
    except json.JSONDecodeError:
        print(
            f"{Fore.LIGHTRED_EX}Error: The file {workflow_file} contains invalid JSON.{Style.RESET_ALL}"
        )
        return None
    except Exception as e:
        print(
            f"{Fore.LIGHTRED_EX}Error loading workflow file: \n{Fore.LIGHTBLACK_EX}{e}{Style.RESET_ALL}"
        )
        return None


async def run_workflow_and_monitor(
    server_addr="127.0.0.1",
    port_num=8188,
    workflow_file="txt_to_img_hello_world_sdxl_api_comfy_cli_ver.json",
):
    global current_prompt_id, server, port
    server = server_addr
    port = port_num

    # First, test connectivity to ComfyUI
    if not test_comfyui_connection(server, port):
        print(
            f"{Fore.LIGHTRED_EX}Failed to connect to ComfyUI server. Please make sure it's running.{Style.RESET_ALL}"
        )
        return False

    # Load the workflow
    workflow_json = load_workflow_from_file(workflow_file)
    if not workflow_json:
        return False

    # Get user confirmation BEFORE connecting to WebSocket or submitting the workflow
    if not get_user_confirmation():
        print("User chose not to proceed. Exiting without submitting workflow.")
        return False

    print("User confirmed. Proceeding with workflow execution...")

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
            api_url, json={"prompt": workflow_json, "client_id": sid}
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
        subscribe_msg = {"op": "subscribe_to_prompt", "data": {"prompt_id": prompt_id}}
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
                                if (
                                    "_meta" in node_data
                                    and "title" in node_data["_meta"]
                                ):
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

            print(
                "All events processed. Check the output folder for your generated image."
            )
            # Clear the prompt ID since execution is complete
            current_prompt_id = None

        except Exception as e:
            print(f"Error monitoring events: {e}")

            # If we encounter an error, attempt to cancel the workflow
            if current_prompt_id:
                cancel_workflow(current_prompt_id)


async def run_continuous_mode(
    server_addr="127.0.0.1", port_num=8188, workflow_file=curr_workflow
):
    """Run in continuous mode - load workflow but don't execute until requested"""

    global server, port, MIDDLEWARE_HTTP_PORT
    server = server_addr
    port = port_num

    # First, test connectivity to ComfyUI
    if not test_comfyui_connection(server, port):
        print(
            f"{Fore.LIGHTRED_EX}Failed to connect to ComfyUI server. Please make sure it's running.{Style.RESET_ALL}"
        )
        return False

    # Load the workflow
    workflow_json = load_workflow_from_file(workflow_file)
    if not workflow_json:
        return False

    # print("Continuous mode active, but no HTTP server started yet.")

    # Start HTTP server
    http_runner = await start_minimal_http_server()
    print(f"{Fore.LIGHTGREEN_EX}Server is now listening on:{Fore.LIGHTBLACK_EX} http://{server}:{MIDDLEWARE_HTTP_PORT} {Style.RESET_ALL}")

    # print("Press Ctrl+C to exit.")

    try:
        # Keep the server running until interrupted
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("Server shutdown requested")
    finally:
        print("Cleaning up resources...")
        await http_runner.cleanup()
    
    return True


# Main execution
if __name__ == "__main__":
    print(
        f"\n{Fore.LIGHTCYAN_EX}Starting ComfyUI workflow executor in {Fore.LIGHTYELLOW_EX}\033[4m{RUN_MODE.upper()}\033[0m{Fore.LIGHTCYAN_EX} mode.{Style.RESET_ALL} (Press Ctrl+C to cancel at any time)"
    )
    try:
        if RUN_MODE == "single_shot":
            # Original behavior: Try to run the workflow from the file
            asyncio.run(
                run_workflow_and_monitor(
                    server_addr=server, port_num=port, workflow_file=curr_workflow
                )
            )
        elif RUN_MODE == "continuous":
            # WIP
            asyncio.run(
                run_continuous_mode(
                    server_addr=server, port_num=port, workflow_file=curr_workflow
                )
            )
    except KeyboardInterrupt:
        # This should be caught by the signal handler, but just in case
        print("\nKeyboard interrupt detected.")
        if current_prompt_id:
            cancel_workflow(current_prompt_id)
    finally:
        print("Script execution complete.")
