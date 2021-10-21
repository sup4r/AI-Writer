########################################################################################################
# AI人工智障写作 - https://github.com/BlinkDL/AI-Writer
########################################################################################################

import math
import json
import random
import time

_DEBUG_LEVEL_ = 2  # 2 = full, 1 = partial, 0 = none
PORT_NUM = 8266

RUN_DEVICE = 'gpu'  # gpu 或 cpu

MODEL_NAME = 'model/ww-102-L12-H12-C768-T512-20210930'
WORD_NAME = 'model/ww-20210821'

min_p_ratio = 0.02  # 这个数字的范围是 0 到 1。数字越大，生成效果越规矩。数字越小，变化越多。

LENGTH_OF_EACH = 20  # 每次写多少字

ctx_len = 512
n_layer = 12
n_head = 12
n_embd = n_head * 64
n_attn = n_embd
n_ffn = n_embd

##############################################################################


def main():
    import sys
    import signal
    from multiprocessing import Process, RawArray, freeze_support, Queue, Lock

    freeze_support()

    queueZ = Queue()
    queueX = Queue()

    process = []
    process.append(Process(target=SocketWorker, args=(queueX, queueZ)))
    process.append(Process(target=NeuralWorker, args=(queueZ, queueX)))

    for p in process:
        p.daemon = True
        p.start()

    def signal_handler(signal, frame):
        for p in process:
            p.terminate()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    for p in process:
        p.join()


def SocketWorker(queueX, queueZ):
    import asyncio
    import websockets
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    USERS = set()

    async def producer():
        hasData = False
        try:
            K, out = queueX.get(timeout=0.05)
            hasData = True
        except:
            pass
        if hasData:
            return (K, out)
        else:
            await asyncio.sleep(0.001)
            if random.random() < -0.003:
                return '[PING]'
            else:
                return ''

    async def producer_handler(websocket, path):
        while True:
            msg = await producer()
            if isinstance(msg, tuple):
                K, msg = msg
                for x in USERS:
                    if x.client_id == K:
                        if _DEBUG_LEVEL_ > 0:
                            print('sent X', K)
                        await x.send(msg)
                        break
            elif msg != '':
                await websocket.send(msg)

    async def consumer(websocket, msg):
        if msg == '[PONG]':
            return
        try:
            msg = json.loads(msg)
            if msg['op'].lower() == 'get':
                if _DEBUG_LEVEL_ > 0:
                    print('get', websocket.client_id, msg['txt'])
                queueZ.put((websocket.client_id, msg['txt']))
        except Exception as e:
            print(e)
            pass

    async def consumer_handler(websocket, path):
        while True:
            msg = await websocket.recv()
            await consumer(websocket, msg)

    async def server(websocket, path):
        websocket.client_id = '%020x' % random.randrange(16**20)
        USERS.add(websocket)
        print("[ws connect]", len(USERS), 'users @',
              time.strftime("%Y %b %d %H:%M:%S", time.localtime(time.time())))
        try:
            await websocket.send('id_' + websocket.client_id)
            consumer_task = asyncio.ensure_future(
                consumer_handler(websocket, path))
            producer_task = asyncio.ensure_future(
                producer_handler(websocket, path))
            done, pending = await asyncio.wait(
                [consumer_task, producer_task],
                return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
        finally:
            USERS.remove(websocket)
            print("[ws disconnect]", len(USERS))

    def srv_exception(loop, context):
        if _DEBUG_LEVEL_ > 1:
            print('exception', loop, context)
        pass

    try:
        start_server = websockets.serve(server, "127.0.0.1", PORT_NUM)
        asyncio.get_event_loop().run_until_complete(start_server)
        asyncio.get_event_loop().set_exception_handler(srv_exception)
        asyncio.get_event_loop().run_forever()
    except Exception as e:
        print('[srv error]', e)


def NeuralWorker(queueZ, queueX):
    from multiprocessing import Process, RawArray, freeze_support, Queue, Lock

    import numpy as np
    import torch
    import torch.nn as nn
    from torch.nn import functional as F

    import src.utils
    from src.model import GPT, GPTConfig

    # src.utils.set_seed(42) # 是否固定随机数（固定后每次运行的生成结果都一样）

    print('\nAI人工智障写作 https://github.com/BlinkDL/AI-Writer')
    print('请关注我的知乎 https://zhuanlan.zhihu.com/p/394766831')
    print('\n声明：模型的训练数据全部来自网文，缺乏生活常识。生成的文字仅供娱乐。请遵守法律法规。')

    print('loading model...')

    with open(WORD_NAME + '.json', "r", encoding="utf-16") as result_file:
        word_table = json.load(result_file)

    vocab_size = len(word_table)

    def train_dataset(): return None
    train_dataset.stoi = {v: int(k) for k, v in word_table.items()}
    train_dataset.itos = {int(k): v for k, v in word_table.items()}
    UNKNOWN_CHAR = train_dataset.stoi['\ue083']

    model = GPT(GPTConfig(vocab_size, ctx_len, n_layer=n_layer,
                n_head=n_head, n_embd=n_embd, n_attn=n_attn, n_ffn=n_ffn))
    if RUN_DEVICE == 'gpu':
        model = model.cuda()
        model.load_state_dict(torch.load(MODEL_NAME + '.pth').state_dict())
    else:
        model.load_state_dict(torch.load(
            MODEL_NAME + '.pth', map_location='cpu').state_dict())

    print('done:', MODEL_NAME, '&', WORD_NAME)

    while True:
        K, Z = queueZ.get()
        # print('neural task', K, Z)

        ttt = time.time()

        context = Z
        context = context.strip().split('\n')
        for c in range(len(context)):
            context[c] = context[c].strip().strip('\u3000')
        context = '\n' + ('\n'.join(context)).strip()
        print('您输入的开头有 ' + str(len(context)) +
              ' 个字。注意，模型只会看最后 ' + str(ctx_len) + ' 个字。')

        NUM_OF_RUNS = 1
        for run in range(NUM_OF_RUNS):

            x = np.array([train_dataset.stoi.get(s, UNKNOWN_CHAR)
                         for s in context], dtype=np.int64)

            real_len = len(x)
            print_begin = 0
            out_txt = ''

            for i in range(LENGTH_OF_EACH):

                if i == 0:
                    print_begin = real_len

                with torch.no_grad():
                    xxx = torch.tensor(
                        x[-ctx_len:], dtype=torch.long)[None, ...]
                    if RUN_DEVICE == 'gpu':
                        xxx = xxx.cuda()
                    out, _ = model(xxx)
                    out[:, :, UNKNOWN_CHAR] = -float('Inf')
                pos = -1 if real_len >= ctx_len else real_len - 1

                if train_dataset.itos[int(x[real_len-1])] == '\n':
                    char = src.utils.sample_logits(
                        out, pos, temperature=1.0, top_p=0.995)
                else:
                    char = src.utils.sample_logits(
                        out, pos, temperature=0.9, min_p_pow=2.0, min_p_ratio=min_p_ratio)

                x = np.append(x, char)
                real_len += 1

                completion = ''.join([train_dataset.itos[int(i)]
                                      for i in x[print_begin:real_len]])
                out_txt += completion
                print_begin = real_len

        outmsg = {}
        outmsg['op'] = 'TXT'
        outmsg['txt'] = out_txt
        queueX.put((K, json.dumps(outmsg, separators=(',', ':'))))

        if _DEBUG_LEVEL_ > 1:
            print(time.time() - ttt, end=' ')
        ttt = time.time()
        if _DEBUG_LEVEL_ > 1:
            print('done Z', K)


if __name__ == "__main__":
    main()