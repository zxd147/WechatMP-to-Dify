import hashlib

from flask import Flask, request, abort


app = Flask(__name__)
TOKEN = 'sk_wechat'

def verify():
    signature = request.args.get('signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')
    echostr = request.args.get('echostr', '')
    # 检查参数是否齐全
    if not all([signature, timestamp, nonce, echostr]):
        abort(400)
    print(f"参数类型: signature={type(signature)}, timestamp={type(timestamp)}, nonce={type(nonce)}, echostr={type(echostr)}"
                    f"参数: : signature={signature}, timestamp={timestamp}, nonce={nonce}, echostr={echostr}")
    # 对 token、timestamp、nonce 进行字典序排序
    tmp_list = [TOKEN, timestamp, nonce]
    tmp_list.sort()
    # 拼接成字符串并进行 sha1 加密
    tmp_str = ''.join(tmp_list)
    print(tmp_str)
    hash_code = hashlib.sha1(tmp_str.encode('utf-8')).hexdigest()
    # 检查加密后的字符串是否与 signature 相等
    if hash_code != signature:
        abort(403)  # 如果不相等，则返回 403 错误
    print(f"success, echostr={type(echostr)}, {echostr}")
    return echostr  # 返回 echostr 参数内容


@app.route('/', methods=['GET'])
def index():
    return verify()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)  # 将后端程序运行在 80 端口
