# pip install requests

import requests
import uuid
import time
import json
import os

# ==================== 配置区域 ====================
# 请将您的有效 token 放在这里，或通过环境变量 QWEN_AUTH_TOKEN 设置
QWEN_AUTH_TOKEN = os.environ.get("QWEN_AUTH_TOKEN")
if not QWEN_AUTH_TOKEN:
    if "token.txt" in os.listdir():
        with open("token.txt", "r") as f:
            QWEN_AUTH_TOKEN = f.read()
    else:
        raise ValueError("请在 token.txt 中填写你的 token")
# 默认模型
DEFAULT_MODEL = "qwen3-235b-a22b"
# =================================================


class QwenClient:
    """
    用于与 chat.qwen.ai API 交互的客户端。
    简单的 Qwen API 客户端，使用 cookie token 请求远程 API。
    """

    def __init__(self, auth_token: str, base_url: str = "https://chat.qwen.ai"):
        self.auth_token = auth_token
        self.base_url = base_url
        self.session = requests.Session()
        # 初始化时设置基本请求头
        self.session.headers.update(
            {
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                "content-type": "application/json",
                "source": "web",
            }
        )
        self.user_info = None
        self.models_info = None
        self.user_settings = None
        self._initialize()

    def _initialize(self):
        """初始化客户端，获取用户信息、模型列表和用户设置"""
        self._update_auth_header()
        try:
            # 获取用户信息
            user_info_res = self.session.get(f"{self.base_url}/api/v1/auths/")
            user_info_res.raise_for_status()
            self.user_info = user_info_res.json()

            # 获取模型列表
            models_res = self.session.get(f"{self.base_url}/api/models")
            models_res.raise_for_status()
            self.models_info = {
                model["id"]: model for model in models_res.json()["data"]
            }

            # 获取用户设置
            settings_res = self.session.get(
                f"{self.base_url}/api/v2/users/user/settings"
            )
            settings_res.raise_for_status()
            self.user_settings = settings_res.json()["data"]

        except requests.exceptions.RequestException as e:
            print(f"客户端初始化失败: {e}")
            raise

    def _update_auth_header(self):
        """更新会话中的认证头"""
        self.session.headers.update({"authorization": f"Bearer {self.auth_token}"})

    def _get_model_id(self, model_name: str) -> str:
        """获取有效的模型 ID"""
        if model_name in self.models_info:
            return model_name
        else:
            print(f"模型 '{model_name}' 未找到，使用默认模型 '{DEFAULT_MODEL}'")
            return DEFAULT_MODEL

    def create_chat(self, model_id: str, title: str = "新对话") -> str:
        """创建一个新的对话"""
        self._update_auth_header()  # 确保 token 是最新的
        url = f"{self.base_url}/api/v2/chats/new"
        payload = {
            "title": title,
            "models": [model_id],
            "chat_mode": "normal",
            "chat_type": "t2t",  # Text to Text
            "timestamp": int(time.time() * 1000),
        }
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            chat_id = response.json()["data"]["id"]
            return chat_id
        except requests.exceptions.RequestException as e:
            raise

    def chat(self, request: dict):
        """
        执行聊天请求。
        返回流式生成器或非流式响应。
        """
        self._update_auth_header()  # 确保 token 是最新的

        # 解析请求参数
        model = request.get("model", DEFAULT_MODEL)
        messages = request.get("messages", [])
        stream = request.get("stream", False)
        enable_thinking = request.get("enable_thinking", True)
        thinking_budget = request.get("thinking_budget", None)

        # 获取模型ID
        model_id = self._get_model_id(model)

        # 创建新会话，拼接所有消息
        formatted_history = "\n\n".join(
            [f"{msg['role']}: {msg['content']}" for msg in messages]
        )
        if messages and messages[0]["role"] != "system":
            formatted_history = "system:\n\n" + formatted_history
        user_input = formatted_history

        chat_id = self.create_chat(model_id, title=f"Chat_{int(time.time())}")
        parent_id = None

        try:
            # 准备请求负载
            timestamp_ms = int(time.time() * 1000)

            # 构建 feature_config
            feature_config = {"output_schema": "phase"}
            feature_config["thinking_enabled"] = enable_thinking
            if enable_thinking and thinking_budget is not None:
                feature_config["thinking_budget"] = thinking_budget

            payload = {
                "stream": True,  # 始终使用流式以获取实时数据
                "incremental_output": True,
                "chat_id": chat_id,
                "chat_mode": "normal",
                "model": model_id,
                "parent_id": parent_id,
                "messages": [
                    {
                        "fid": str(uuid.uuid4()),
                        "parentId": parent_id,
                        "childrenIds": [str(uuid.uuid4())],
                        "role": "user",
                        "content": user_input,
                        "user_action": "chat",
                        "files": [],
                        "timestamp": timestamp_ms,
                        "models": [model_id],
                        "chat_type": "t2t",
                        "feature_config": feature_config,
                        "extra": {"meta": {"subChatType": "t2t"}},
                        "sub_chat_type": "t2t",
                        "parent_id": parent_id,
                    }
                ],
                "timestamp": timestamp_ms,
            }

            # 添加必要的头
            headers = {"x-accel-buffering": "no"}  # 对于流式响应很重要

            url = f"{self.base_url}/api/v2/chat/completions?chat_id={chat_id}"

            if stream:
                # 流式请求
                def generate():
                    try:
                        # 使用流式请求，并确保会话能正确处理连接
                        with self.session.post(
                            url, json=payload, headers=headers, stream=True
                        ) as r:
                            r.raise_for_status()
                            finish_reason = "stop"
                            reasoning_text = ""  # 用于累积 thinking 阶段的内容
                            assistant_content = ""  # 用于累积assistant回复内容
                            has_sent_content = False  # 标记是否已经开始发送 answer 内容
                            current_response_id = None  # 当前回复ID

                            for line in r.iter_lines(decode_unicode=True):
                                # 检查标准的 SSE 前缀
                                if line.startswith("data: "):
                                    data_str = line[6:]  # 移除 'data: '
                                    if data_str.strip() == "[DONE]":
                                        yield "data: [DONE]\n\n"
                                        break
                                    try:
                                        data = json.loads(data_str)

                                        # 提取response_id
                                        if "response.created" in data:
                                            current_response_id = data[
                                                "response.created"
                                            ].get("response_id")

                                        # 处理 choices 数据
                                        if (
                                            "choices" in data
                                            and len(data["choices"]) > 0
                                        ):
                                            choice = data["choices"][0]
                                            delta = choice.get("delta", {})

                                            # --- 重构逻辑：清晰区分 think 和 answer 阶段 ---
                                            phase = delta.get("phase")
                                            status = delta.get("status")
                                            content = delta.get("content", "")

                                            # 1. 处理 "think" 阶段
                                            if phase == "think":
                                                if status != "finished":
                                                    reasoning_text += content
                                                # 注意：think 阶段的内容不直接发送，只累积

                                            # 2. 处理 "answer" 阶段 或 无明确 phase 的内容 (兼容性)
                                            elif phase == "answer" or (
                                                phase is None and content
                                            ):
                                                # 一旦进入 answer 阶段或有内容，标记为已开始
                                                has_sent_content = True
                                                assistant_content += (
                                                    content  # 累积assistant回复
                                                )

                                                # 返回内容
                                                chunk = {"content": content}
                                                if reasoning_text:
                                                    chunk["reasoning"] = reasoning_text
                                                    reasoning_text = ""
                                                yield f"data: {json.dumps(chunk)}\n\n"

                                            # 3. 处理结束信号 (通常在 answer 阶段的最后一个块)
                                            if status == "finished":
                                                finish_reason = delta.get(
                                                    "finish_reason", "stop"
                                                )

                                    except json.JSONDecodeError:
                                        continue
                    except requests.exceptions.RequestException as e:
                        # 发送错误信息
                        error_chunk = {"error": f"请求失败: {str(e)}"}
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                    finally:
                        pass

                return generate()

            else:
                # 非流式请求: 聚合响应
                response_text = ""
                reasoning_text = ""

                try:
                    with self.session.post(
                        url, json=payload, headers=headers, stream=True
                    ) as r:
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=True):
                            # 检查完整的 SSE 前缀
                            if line.startswith("data: "):
                                data_str = line[6:]  # 移除 'data: '
                                if data_str.strip() == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)

                                    # 提取response_id
                                    if "response.created" in data:
                                        current_response_id = data[
                                            "response.created"
                                        ].get("response_id")

                                    # 处理 choices 数据来构建最终回复
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})

                                        # 累积 "think" 阶段的内容
                                        if delta.get("phase") == "think":
                                            if delta.get("status") != "finished":
                                                reasoning_text += delta.get(
                                                    "content", ""
                                                )

                                        # 只聚合 "answer" 阶段的内容
                                        if delta.get("phase") == "answer":
                                            if delta.get("status") != "finished":
                                                response_text += delta.get(
                                                    "content", ""
                                                )

                                except json.JSONDecodeError:
                                    # 忽略无法解析的行
                                    continue

                    # 构造响应
                    response = {"content": response_text}
                    if reasoning_text:
                        response["reasoning"] = reasoning_text
                    return response
                finally:
                    pass

        except requests.exceptions.RequestException as e:
            return {"error": f"请求失败: {str(e)}"}


# 初始化客户端
qwen_client = QwenClient(auth_token=QWEN_AUTH_TOKEN)


def get_models():
    """获取可用模型列表"""
    try:
        models = []
        for model_id, model_info in qwen_client.models_info.items():
            models.append(
                {
                    "id": model_info["info"]["id"],
                    "name": model_info["info"].get("name", model_id),
                }
            )
        return models
    except Exception as e:
        print(f"获取模型列表失败: {e}")
        return []


if __name__ == "__main__":
    # 示例用法
    print("Qwen 客户端初始化完成")

    # 示例：获取模型列表
    models = get_models()
    print(f"可用模型 ID: ")
    for model in models:
        print(f"ID: {model['id']}, Name: {model['name']}")
    print(f"当前模型: {DEFAULT_MODEL}")

    # 示例：发送聊天请求
    request = {
        "model": "qwen3-235b-a22b",
        "messages": [{"role": "user", "content": "你好！"}],
        "stream": False,
    }

    response = qwen_client.chat(request)
    if "content" in response:
        print(f"AI回复: {response['content']}")
    else:
        print(f"请求失败: {response.get('error', '未知错误')}")
