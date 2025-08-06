# Qwen API

A Python API wrapper for interacting with Qwen chat service.

## Token Retrieval

To use this API, you need to obtain your authentication token from the Qwen chat platform:

1. **Navigate to chat.qwen.ai** and log in to your account

2. **Open Developer Tools** by pressing F12

3. **Find the "Applications" tab** at the top of the developer tools panel

4. **Locate "Local Storage"** in the left sidebar and expand the dropdown menu

5. **Select chat.qwen.ai** from the list

6. **Find the "token" value** in the right panel and copy the entire value - this is your `QWEN_AUTH_TOKEN`

## Basic Usage

```python
from qwen_api import QwenAPI

# Initialize the API client with your token
client = QwenAPI(auth_token="YOUR_QWEN_AUTH_TOKEN")

# Send a message
response = client.send_message("Hello, how can you help me today?")
print(response)

# Create a new conversation
conversation = client.create_conversation()

# Continue an existing conversation
response = client.send_message(
    "What's the weather like?", 
    conversation_id=conversation.id
)
```

## Installation

```bash
pip install -r requirements.txt
```

## Environment Variables

For security, it's recommended to store your token as an environment variable:

```bash
export QWEN_AUTH_TOKEN="your_token_here"
```

Then in your code:

```python
import os
from qwen_api import QwenAPI

client = QwenAPI(auth_token=os.getenv("QWEN_AUTH_TOKEN"))
```

## Requirements

- Python 3.7+
- Required dependencies listed in `requirements.txt`

## License

MIT License