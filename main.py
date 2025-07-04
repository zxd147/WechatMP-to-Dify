import asyncio
import hashlib
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import aiohttp
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from loguru import logger

# 移除所有默认的处理器
logger.remove()
logger.bind()
log_format = "<g>{time:MM-DD HH:mm:ss}</g> <lvl>{level:<9}</lvl> \n{message}"
logger.add(sys.stdout, level="INFO", format=log_format, backtrace=True, diagnose=True)
api_logger = logger

# 在模块加载时打印启动时间
ts = time.time()
formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
api_logger.info(f"启动时间: {formatted_time}")
with open('config.json', 'r') as f:
    config = json.load(f)

host = config["host"]
port = config["port"]
model = config["model"]
semaphore = asyncio.Semaphore(config["semaphore_limit"])
llm_param = config["llm_param"]
llm_models = config["llm_models"]
llm_model = llm_models[model]
token = config["auth"].get("token")

app = FastAPI()


async def process_message(query):
    param = llm_param
    param["query"] = query
    headers = config["header"]
    chat_url = llm_model["base_url"]
    headers["Authorization"] = llm_model["api_key"]
    logs = f"Dify request param: ---\n{json.dumps(param, ensure_ascii=False, indent=None)}\n---"
    api_logger.debug(logs)

    answer = ''
    response_data = ''
    try:
        async with semaphore:
            async with aiohttp.ClientSession() as session:
                async with session.post(chat_url, headers=headers, data=json.dumps(param), timeout=10) as response:
                    if response.status == 200:
                        code = 0
                        messages = 'Dify response session successfully'
                        if response.content_type == 'application/json':
                            response_data = await response.json()
                            answer = response_data.get('answer', '')
                        elif response.content_type == 'text/event-stream':
                            encoding = response.charset
                            async for line in response.content:
                                json_string = line.decode(encoding).strip().replace('data: ', '')
                                response_data += json_string + '\n'
                                if json_string == "[DONE]":
                                    continue
                                if json_string:
                                    try:
                                        data = json.loads(json_string)
                                        content = data.get('answer', '')
                                        if content:
                                            answer += content
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
    if answer != '':
        logs = f'{messages}, response_data: ===\n{response_data}\n==='
        api_logger.debug(logs)
    else:
        if code != -1:
            if response_data:
                messages = f"{messages}, ChatGPT response text is empty, response_data: ===\n{response_data}\n==="
        api_logger.error(messages)
    return answer


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


def verify(signature, timestamp, nonce, echostr):
    """
    微信服务器验证核心逻辑
    """
    api_logger.debug(f"参数类型: signature={type(signature)}, timestamp={type(timestamp)}, nonce={type(nonce)}, echostr={type(echostr)}, "
                    f"参数: : signature={signature}, timestamp={timestamp}, nonce={nonce}, echostr={echostr}")
    if not all([signature, timestamp, nonce, echostr]):
        raise HTTPException(status_code=400, detail="missing param")
    # 对 token、timestamp、nonce 进行字典序排序
    tmp_list = [token, timestamp, nonce]
    tmp_list.sort()
    # 拼接成字符串并进行 sha1 加密
    tmp_str = ''.join(tmp_list)
    api_logger.info(tmp_str)
    hash_code = hashlib.sha1(tmp_str.encode()).hexdigest()

    if hash_code != signature:
        raise HTTPException(status_code=403, detail="Invalid signature")
    api_logger.debug(f"success, echostr={type(echostr)}, {echostr}")
    return echostr

# 注册API路由
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.api_route("/", methods=["GET", "POST"])
@app.api_route("/health", methods=["GET", "POST"])
async def health():
    """index."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    health_data = {"service": "WechatMP-to-Dify", "status": "running", "timestamp": timestamp}
    # 返回JSON格式的响应
    return JSONResponse(content=health_data, status_code=200)

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico", headers={"Cache-Control": "public, max-age=3600"})

@app.get("/api/v1/wechat_mp/dify")
async def wechat_mp_auth(
        request: Request,
        signature: str = Query(..., alias="signature"),
        timestamp: str = Query(..., alias="timestamp"),
        nonce: str = Query(..., alias="nonce"),
        echostr: int = Query(..., alias="echostr")
):
    """微信验证接口入口"""
    echostr = verify(signature, timestamp, nonce, echostr)
    return echostr


@app.post('/api/v1/wechat_mp/dify')
async def wechat_mp_chat(request: Request):
    # 处理微信服务器推送的消息
    xml_data = await request.body()
    msg = parse_message(xml_data)
    api_logger.info(f'Request: {msg}')  # 查看消息解析是否正确
    # 回复文本消息示例
    query = msg['Content']
    response_content = await process_message(query)
    api_logger.info(f'Response: {response_content}')  # 查看消息解析是否正确
    # 返回前端
    response_xml = generate_reply(msg['FromUserName'], msg['ToUserName'], int(time.time()), response_content)
    return Response(content=response_xml, media_type="application/xml")


async def test():
    query = "你好"
    answer = await process_message(query)
    print(answer)


if __name__ == '__main__':
    uvicorn.run(app, host=host, port=port)
