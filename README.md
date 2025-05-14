# README

## ComfyUI Workflow Executor

### Example for API Usage

A Python test script for executing ComfyUI workflows via the API with real-time monitoring.

### Overview

This script allows you to:

1. Load and execute a ComfyUI workflow from JSON files, exported from ComfyUI (after __dev__ mode is enabled you can select `export _Export(API)`) and store the json file in the root directory as `workflow_api.json`.
2. Monitor execution progress in real-time via WebSocket
3. Interrupt workflow execution when needed

Notes:

1. There is an example [workflow.json](workflow.json) present here. You an load that in your ComfyUI and check it out. It's a basic text to image workflow that uses SDXL4.0 checkpoint (There are notes in the workflow from where you can download the checkpoints in the right location)
2. The respective exported [workflow_api.json](workflow_api.json) for convenience. But better you export it and do customization if needed.

### Requirements

1. Python 3.8+
2. ComfyUI server running (default: localhost:8000)
3. Required Python packages:
   1. websockets
   2. requests
   3. asyncio

### Installation

> Tested on MacOS

1. Clone the repo
2. Load the wokflow in Comfy UI (install dependencies following the workflow notes)
3. export the workflow api and rename it as `workflow.json` and store it here in the root of the repo.
4. Then:

```bash
python3 -m venv venv
python3 -m pip install -r requirements.txt
python3 comfyui-workflow-runner.py
```

### Understanding

```python
curr_workflow = "workflow_api.json" # Is where you supply the workflow file
RUN_MODE = "continuous"  # Options: "single_shot" or "continuous"
AUTO_EXECUTE_ON_UPLOAD = False  # To control auto-execution on image upload
```

### Example Output

> Ignore the first few frames where I struggle with the correct imports and installations ... 😵

![alt text](_assets/running.gif)

### What is the script doing? 

> If mermaid is not visisble in your markdown renderer, checkout the [png](_assets/script_test_api_flow.png) /[svg](_assets/script_test_api_flow.svg) / [UML](https://www.planttext.com?text=RLFBRkCm3BpxAtXC3yNUwyDsiUtsWSKsg5FqM3Wo7GknHK6ay_ZxfMmb2f1UR9ap7758-fwb3Z8EVI5MUeJVDBJ7ZnVufB1jUzfhm4cW7YeJh9UYcFZ5tL-g6zYVIA_LspzeROzbOLjO_D4JuC6oyCyRa0uTB8x8DmN0tODbtzV7dClZCDJXM4Rm5s-XfG0ZOm13hhLXgCMIYsXK_hW0hhHLGAjrQ0I4u1FN5PajIZb3xsZGxX0OcLKHNXuIK8thmKekQ6ThU5wjbh1ygrPHwOSFDFYJpXCAp84lsq2h9mZ8dXnZ5cJjrXfZyao5qJUr8C-CwR7lOfSMZmSqOxIejWRVew3QiWmBHxCd5Lm6CbfrjWIuGoT93S2H80IxwIG506wr_qduQnxPTuYfJOVDDUGs5p5ri567V4NxBZEA9Xy9HDTC1QRFz3eFqph144P_lIh9V1K5pgCuqylCU3p4yLdfOD0owmrcZ8LyhiEsHJfDpS-pqENm54HtqSH6jsD_caRQFUmPyqZoZJJ69DsVQQScvdJD9VyahdLJA8kPC1LshsVzzVu3)
> 

```mermaid
flowchart TD
    start([Start]) --> load[Load workflow JSON file]
    load --> fileCheck{File exists?}
    
    fileCheck -- Yes --> display[Display workflow summary]
    fileCheck -- No --> reportErr[Report error]
    reportErr --> stop([Stop])
    
    display --> askUser[Ask for user confirmation]
    askUser --> userCheck{User confirms?}
    
    userCheck -- No --> exitNoSub[Exit without submission]
    exitNoSub --> stop
    
    userCheck -- Yes --> connect[Connect to WebSocket]
    connect --> receiveID[Receive session ID]
    receiveID --> submitWork[Submit workflow via HTTP POST to /prompt]
    submitWork --> getPromptID[Get prompt_id from response]
    getPromptID --> subscribe[Subscribe to prompt updates]
    
    subscribe --> execCheck{Execution complete?}
    
    execCheck -- No --> processEvents[Process WebSocket events]
    processEvents --> interruptCheck{User interrupts?}
    
    interruptCheck -- Yes --> sendInterrupt[Send POST to /interrupt]
    sendInterrupt --> exitMsg[Exit with message]
    exitMsg --> stop
    
    interruptCheck -- No --> execCheck
    
    execCheck -- Yes --> reportSuccess[Report successful completion]
    reportSuccess --> stop
    
    %% Add note for WebSocket events
    processEvents -.- eventNote[["
        WebSocket events:
        - execution_start
        - execution_cached
        - executing
        - progress
        - executed
        - execution_complete
    "]]
    
    classDef note fill:#ffffcc,stroke:#999,stroke-width:1px;
    class eventNote note;
```

---

### MODE Architechture breakdowns

SINGLE SHOT MODE

```mermaid
sequenceDiagram
    participant User
    participant Script as ComfyUI Workflow Runner
    participant ComfyUI as ComfyUI Server (Port 8188)
    
    User->>Script: Launch script with workflow file
    Script->>Script: Load workflow JSON from file
    
    Script->>User: Display workflow summary
    Script->>User: Ask for confirmation
    User->>Script: Confirm execution (y/yes)
    
    Script->>ComfyUI: Connect to WebSocket
    ComfyUI-->>Script: Establish connection, return session ID
    
    Script->>ComfyUI: POST /prompt with workflow
    ComfyUI->>ComfyUI: Begin workflow execution
    ComfyUI-->>Script: Return prompt_id
    
    Script->>ComfyUI: Subscribe to prompt updates via WebSocket
    
    ComfyUI->>Script: WebSocket: execution_start event
    ComfyUI->>Script: WebSocket: executing node events
    ComfyUI->>Script: WebSocket: progress events
    
    loop Until execution completes
        ComfyUI->>Script: WebSocket: node execution events
        Script->>Script: Log progress to console
    end
    
    ComfyUI->>Script: WebSocket: execution_complete event
    
    Script->>Script: Log completion
    Script->>User: Exit script
    
    alt User interrupts (Ctrl+C)
        User->>Script: Send interrupt signal
        Script->>ComfyUI: POST /interrupt
        ComfyUI->>ComfyUI: Stop execution
        Script->>User: Exit script
    end
```

---

CONTINUE MODE

```mermaid
sequenceDiagram
    participant Client
    participant Middleware as Our Middleware (Port 8189)
    participant ComfyUI as ComfyUI Server (Port 8188)
    
    note over Client,ComfyUI: Initial Setup Phase
    Client->>Middleware: Script starts in "continuous" mode
    Middleware->>ComfyUI: Test connectivity (/system_stats)
    ComfyUI-->>Middleware: Return system info
    Middleware->>Middleware: Load workflow from file
    Middleware->>ComfyUI: Connect to WebSocket
    ComfyUI-->>Middleware: Establish connection, get session ID
    
    note over Client,ComfyUI: Workflow Update Phase
    Client->>Middleware: POST /upload/image (with image data)
    Middleware->>Middleware: Save image to temp file
    Middleware->>ComfyUI: Forward image to /upload/image
    ComfyUI->>ComfyUI: Store image
    ComfyUI-->>Middleware: Return image name & info
    Middleware->>Middleware: Update workflow JSON with new image
    Middleware-->>Client: Return success message
    
    Client->>Middleware: POST /update/prompt (with node_id and text)
    Middleware->>Middleware: Update prompt in workflow JSON
    Middleware-->>Client: Return success message
    
    note over Client,ComfyUI: Execution Phase
    Client->>Middleware: GET /queue (trigger execution)
    Middleware->>ComfyUI: POST /prompt with modified workflow
    ComfyUI->>ComfyUI: Begin workflow execution
    ComfyUI-->>Middleware: Return prompt_id
    Middleware-->>Client: Return "execution started" message
    
    note over Client,ComfyUI: Monitoring Phase
    ComfyUI->>Middleware: WebSocket: execution_start event
    ComfyUI->>Middleware: WebSocket: executing node events
    ComfyUI->>Middleware: WebSocket: progress events
    
    alt Interrupt Execution
        Client->>Middleware: POST /interrupt
        Middleware->>ComfyUI: POST /interrupt
        ComfyUI->>ComfyUI: Stop execution
        ComfyUI-->>Middleware: Return success
        Middleware-->>Client: Return "interrupted" message
    else Complete Execution
        ComfyUI->>Middleware: WebSocket: execution_complete event
        Middleware->>Middleware: Log completion, reset status
        note right of Client: Generated image available in ComfyUI output folder
    end
```

CONTINIOUS MODE MIDDLE WARE ARCHITECHTURE

```mermaid
graph TD
    subgraph "Client"
        C1["External Client\n(curl, browser, etc.)"]
    end

    subgraph "Our Middleware (Port 8189)"
        MS["HTTP Server"]
        MW["Workflow Manager"]
        MC["ComfyUI Client"]
        WS["WebSocket Client"]
    end

    subgraph "ComfyUI Server (Port 8188)"
        CS["ComfyUI HTTP Server"]
        CWS["ComfyUI WebSocket Server"]
        CE["Execution Engine"]
        CFS["File Storage"]
    end

    %% Client to Middleware interactions
    C1 -->|"1. POST /upload/image\n(with image data)"| MS
    C1 -->|"2. POST /update/prompt\n(with prompt text)"| MS
    C1 -->|"3. GET /queue\n(trigger execution)"| MS
    C1 -->|"4. POST /interrupt\n(cancel execution)"| MS

    %% Internal middleware flow
    MS -->|"Process requests"| MW
    MW -->|"Store & update workflow"| MW

    %% Middleware to ComfyUI interactions
    MC -->|"Forward image\nto /upload/image"| CS
    MC -->|"Submit workflow\nvia /prompt"| CS
    MC -->|"Request interrupt\nvia /interrupt"| CS

    %% WebSocket communication
    WS <-->|"Monitor execution\nvia WebSocket"| CWS
    CWS <-->|"Send execution\nevents"| CE

    %% ComfyUI internal flow
    CS -->|"Forward requests"| CE
    CE -->|"Store images"| CFS

    %% Response flows
    CS -->|"Return responses"| MC
    MC -->|"Process responses"| MS
    MS -->|"Return results to client"| C1

    %% Additional notes
    classDef middleware fill:#b3e0ff,stroke:#0066cc
    classDef comfyui fill:#ffcccc,stroke:#990000
    classDef client fill:#d9f2d9,stroke:#006600

    class MS,MW,MC,WS middleware
    class CS,CWS,CE,CFS comfyui
    class C1 client
```

### Features

1. Interactive Confirmation: Asks before executing to avoid accidental runs
2. Real-time Monitoring: Shows which nodes are executing and progress percentage
3. Graceful Cancellation: Press Ctrl+C to cancel execution
4. Automatic Session Handling: Uses WebSocket session ID for proper workflow tracking

---

### What are the API's available to us and have been implemented here?

[Check the API docs here](docs/COMFYUI_API.md)

---

### License

[MIT](LICENSE)
