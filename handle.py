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
TOKEN = 'sk_wechat'
model = 'deepseek'

app = Flask(__name__)


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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)  # 将后端程序运行在 80 端口
