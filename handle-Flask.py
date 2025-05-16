import asyncio
import hashlib
import json
import sys
import time
import xml.etree.ElementTree as ET

import aiohttp
from flask import Flask, request, make_response, abort
from loguru import logger


# 移除所有默认的处理器
logger.remove()
logger.bind()
log_format = "<g>{time:MM-DD HH:mm:ss}</g> <lvl>{level:<9}</lvl> \n{message}"
logger.add(sys.stdout, level="INFO", format=log_format, backtrace=True, diagnose=True)
api_logger = logger

# 在模块加载时打印启动时间
timestamp = time.time()
formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
api_logger.info(f"启动时间: {formatted_time}")

with open('config.json', 'r') as f:
    config = json.load(f)

semaphore = asyncio.Semaphore(config["concurrency"]["semaphore_limit"])
api_models = config["api_models"]
api_model = api_models[config["concurrency"]["model"]]
TOKEN = config["auth"]
model = 'deepseek'

app = Flask(__name__)


async def process_message(query):
    param = config["api_param"]
    param["query"] = query
    headers = config["header"]
    chat_url = api_model["base_url"]
    headers["Authorization"] = api_model["api_key"]
    logs = f"Dify request param: ---\n{json.dumps(param, ensure_ascii=False, indent=None)}\n---"
    api_logger.debug(logs)

    answer = ''
    response_data = ''
    try:
        async with semaphore:  # 整个函数的执行都受到信号量的控制
            async with aiohttp.ClientSession() as session:
                # 准备参数并发起请求
                async with session.post(chat_url, headers=headers, data=json.dumps(param), timeout=10) as response:
                    if response.status == 200:
                        code = 0
                        messages = 'Dify response session successfully'
                        if response.content_type == 'application/json':
                            response_data = await response.json()  # 如果是 JSON，直接解析
                            answer = response_data.get('answer', '')
                        elif response.content_type == 'text/event-stream':
                            encoding = response.charset
                            async for line in response.content:
                                json_string = line.decode(encoding).strip().replace('data: ', '')
                                response_data += json_string + '\n'
                                if json_string == "[DONE]":
                                    continue
                                if json_string:  # 检查内容是否为空
                                    try:
                                        # 尝试解析为 JSON 对象
                                        data = json.loads(json_string)
                                        # 提取content
                                        content = data.get('answer', '')
                                        if content:  # 如果content不为空
                                            answer += content  # 添加到最终内容中
                                    except json.JSONDecodeError:
                                        code = -1
                                        messages = f"{messages}, JSONDecodeError, Dify Data Invalid JSON: {json_string}."
                                        api_logger.error(messages)
                        else:
                            code = -1
                            messages = f"{messages}, Unknown response.content_type: {response.content_type}"
                    else:
                        code = -1
                        messages = f'Dify response failed with status code: {response.status}. '
    except (asyncio.TimeoutError, json.JSONDecodeError, KeyError, Exception) as e:
        error_type = type(e).__name__
        code = -1
        messages = f'{error_type}: {e}'
    answer = answer[2:].strip() if answer[:2] in ("0:", "1:") else answer
    # 去除前两个字符
    if answer != '':
        logs = f'{messages}, response_data: ===\n{response_data}\n==='
        api_logger.debug(logs)
    else:
        if code != -1:
            code = -1
            if response_data:
                messages = f"{messages}, ChatGPT response text is empty, response_data: ===\n{response_data}\n==="
        api_logger.error(messages)
    return answer


async def test():
    query = "你好"
    answer = await process_message(query)
    print(answer)


def parse_message(xml):
    """解析微信服务器发来的消息"""
    root = ET.fromstring(xml)
    msg = {}
    for child in root:
        msg[child.tag] = child.text
    return msg


def generate_reply(from_user, to_user, tim, content):
    """生成回复消息的XML格式"""
    reply = f"""
    <xml>
      <ToUserName><![CDATA[{from_user}]]></ToUserName>
      <FromUserName><![CDATA[{to_user}]]></FromUserName>
      <CreateTime>{tim}</CreateTime>
      <MsgType><![CDATA[text]]></MsgType>
      <Content><![CDATA[{content}]]></Content>
    </xml>
    """
    return reply


def verify():
    signature = request.args.get('signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')
    echostr = request.args.get('echostr', '')
    # 检查参数是否齐全
    if not all([signature, timestamp, nonce, echostr]):
        abort(400)
    # 对 token、timestamp、nonce 进行字典序排序
    tmp_list = [TOKEN, timestamp, nonce]
    tmp_list.sort()
    # 拼接成字符串并进行 sha1 加密
    tmp_str = ''.join(tmp_list)
    hash_code = hashlib.sha1(tmp_str.encode('utf-8')).hexdigest()
    # 检查加密后的字符串是否与 signature 相等
    if hash_code != signature:
        abort(403)  # 如果不相等，则返回 403 错误
    return echostr  # 返回 echostr 参数内容


@app.route('/', methods=['GET'])
def index():
    return verify()


@app.route('/', methods=['POST'])  # 微信后台与服务器默认通过 POST 方法交互
def wechat_auth():
    # 处理微信服务器推送的消息
    xml_data = request.data  # 这个消息是加过密的，所以不能直接解析成字典
    msg = parse_message(xml_data)
    api_logger.info(msg)  # 查看消息解析是否正确
    # 回复文本消息示例
    query = msg['Content']
    response_content = process_message(query)
    # 返回前端
    response_xml = generate_reply(msg['FromUserName'], msg['ToUserName'], int(time.time()), response_content)
    return make_response(response_xml)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)  # 将后端程序运行在 80 端口
