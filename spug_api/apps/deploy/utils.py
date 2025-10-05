# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import json
import os
import uuid
from concurrent import futures
from functools import partial
from logging import debug
from time import sleep, time

import requests
from django.conf import settings
from django.db import close_old_connections
from django_redis import get_redis_connection
from requests.auth import HTTPBasicAuth

from apps.config.utils import compose_configs
from apps.deploy.helper import Helper, SpugError
from apps.deploy.models import DeployRequest
from apps.host.models import Host
from apps.repository.models import Repository
from apps.repository.utils import dispatch as build_repository
from apps.setting.models import Setting
from libs.utils import AttrDict, human_time, render_str

REPOS_DIR = settings.REPOS_DIR
BUILD_DIR = settings.BUILD_DIR


def dispatch(req, fail_mode=False):
    rds = get_redis_connection()
    rds_key = f'{settings.REQUEST_KEY}:{req.id}'
    if fail_mode:
        req.host_ids = req.fail_host_ids
    req.fail_mode = fail_mode
    req.host_ids = json.loads(req.host_ids)
    req.fail_host_ids = req.host_ids[:]
    helper = Helper.make(rds, rds_key, req.host_ids if fail_mode else None)

    try:
        api_token = uuid.uuid4().hex
        rds.setex(api_token, 60 * 60, f'{req.deploy.app_id},{req.deploy.env_id}')
        env = AttrDict(
            SPUG_APP_NAME=req.deploy.app.name,
            SPUG_APP_KEY=req.deploy.app.key,
            SPUG_APP_ID=str(req.deploy.app_id),
            SPUG_REQUEST_ID=str(req.id),
            SPUG_REQUEST_NAME=req.name,
            SPUG_DEPLOY_ID=str(req.deploy.id),
            SPUG_ENV_ID=str(req.deploy.env_id),
            SPUG_ENV_KEY=req.deploy.env.key,
            SPUG_VERSION=req.version,
            SPUG_BUILD_VERSION=req.spug_version,
            SPUG_DEPLOY_TYPE=req.type,
            SPUG_API_TOKEN=api_token,
            SPUG_REPOS_DIR=REPOS_DIR,
        )
        # append configs
        configs = compose_configs(req.deploy.app, req.deploy.env_id)
        configs_env = {f'_SPUG_{k.upper()}': v for k, v in configs.items()}
        env.update(configs_env)

        # 在 dispatch 函数中修改条件判断
        if req.deploy.extend == '1':
            _ext1_deploy(req, helper, env)
        elif req.deploy.extend == '2':
            _ext2_deploy(req, helper, env)
        else:  # extend == '3'
            _ext3_deploy(req, helper, env)
    except Exception as e:
        req.status = '-3'
        raise e
    finally:
        close_old_connections()
        DeployRequest.objects.filter(pk=req.id).update(
            status=req.status,
            repository=req.repository,
            fail_host_ids=json.dumps(req.fail_host_ids),
        )
        helper.clear()
        Helper.send_deploy_notify(req)

# 编写 _ext3_deploy方法
def _ext3_deploy(req, helper, env):
    rds = get_redis_connection()
    # debug('_ext_deploy',req)
    extend_obj = req.deploy.extend_obj
    jenkins_config = Setting.objects.get(key='jenkins_config')
    # 将str类型的jenkins_url转换为json
    jenkins_url = json.loads(jenkins_config.value)['url']
    # 确保 URL 包含协议前缀
    if not jenkins_url.startswith(('http://', 'https://')):
        jenkins_url = 'http://' + jenkins_url

    try:
        # 获取 Jenkins crumb
        crumb_url = f"{jenkins_url.rstrip('/')}/crumbIssuer/api/json"
        # 设置 Basic Auth 认证信息
        auth = HTTPBasicAuth('zhujing', '118e1f6214e99c9bb39a9fe779bf1e2fa8')

        # 请求 Jenkins crumb
        # 使用 POST 请求 Jenkins crumb
        crumb_response = requests.post(crumb_url, auth=auth, timeout=30)
        crumb_response.raise_for_status()
        debug('crumb_response', crumb_response.json())
        crumb_data = crumb_response.json()
        crumb_field = crumb_data['crumbRequestField']  # 例如: "Jenkins-Crumb"
        crumb_value = crumb_data['crumb']  # 例如: "55b721245b33f1c8b1227237c31743ddfcf77e6248047e7223a3c49a5cfac596"
        # 获取job_url
        debug('crumb_value', crumb_value)

        # 准备触发构建的请求
        build_url = f"{jenkins_url.rstrip('/')}/job/pipeline-scm-template/buildWithParameters"

        # 设置请求头，包含 crumb 和认证信息
        headers = {
            crumb_field: crumb_value,  # 使用从API获取的实际字段名和值
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        # 如果需要传递参数，可以在这里添加
        params = {'name': 'zhujing'}  # 如果配置了构建令牌
        build_url += "?" + "&".join([f"{k}={v}" for k, v in params.items()])

        # 触发 Jenkins 构建，此时返回响应头
        build_response = requests.post(build_url, headers=headers, auth=auth, timeout=30)
        # 获取响应头Location
        build_location = build_response.headers.get('Location')
        # build_location后缀增加/api/json获取 executable下number，这个是真实的构建号
        print('build_location',build_location)
        build_url = build_location + "api/json"
        # 这里加一个循环，可能获取不到，这里加一个循环，最多尝试5次
        build_response = None;
        build_number = None;
        start = 0
        # 修改获取构建号的循环逻辑
        for i in range(10):  # 增加尝试次数
            build_response = requests.get(build_url, headers=headers, auth=auth, timeout=30)
            build_response.raise_for_status()

            response_data = build_response.json()
            # 检查是否已经有executable字段
            if 'executable' in response_data and 'number' in response_data['executable']:
                # TODO: 需要和
                build_number = response_data['executable']['number']
                break
            debug(f'等待构建开始，第{i + 1}次尝试...')
            sleep(3)  # 增加等待时间
        # 这里需要获取返回的jenkins任务队列，获取真实的build_number
        build_number = build_response.json()['executable']['number']
        #  断言build_number不为空
        assert build_number is not None, '构建失败'

        # 推送到websockt 初始化信息
        # 这里可能要重构任务名
        helper.send_info('local', f'Jenkins任务已触发，真实任务构建号为: {build_number}\r\n')
        log_url = f"{jenkins_url.rstrip('/')}/job/pipeline-scm-template/{build_number}/logText/progressiveText"
        start = 0
        #  拼接状态请求 stage url
        stage_url=f"{jenkins_url.rstrip('/')}/job/pipeline-scm-template/{build_number}/wfapi/describe"
    #  实时获取jenkins日志
        # 循环获取日志数据直到没有更多数据
        # 该循环持续从服务器获取日志信息，直到服务器返回没有更多数据为止
        # while True:
        #     resp = requests.get(log_url, auth=auth, params={'start': start})
        #     # 获取状态响应结果
        #     stage_res = requests.get(stage_url, auth=auth)
        #     print('stage_res',stage_res.json())
        #     requests.get(log_url, auth=auth)
        #     # print(resp.text, end="")
        #     helper.send_info('local', resp.text)
        #     more_data = resp.headers.get("X-More-Data")
        #     text_size = int(resp.headers.get("X-Text-Size", 0))
        #     start = text_size
        #     # 检查是否还有更多数据，如果没有则退出循环
        #     if more_data != "true":
        #         break
        #     sleep(1)
    #    循环监测stage,获取stages字段列表，间隔1秒

    #  输出 jenkins stage状态逻辑
        build_status = 'IN_PROGRESS'
        while build_status == 'IN_PROGRESS':
            stage_res = requests.get(stage_url, auth=auth)
            stage_data = stage_res.json()
            #   获取stages字段，判断stages length
            status = stage_data['status']
            #  判断status是否SUCCESS，如果是则跳出循环
            if status == 'SUCCESS':
                helper.send_info('local', f'Jenkins任务构建完成！\r\n')
                build_status = 'SUCCESS'
                req.status = '3'
            if 'stages' in stage_data:
                stages = stage_data['stages']
                # 获取stages数组长度
                stage_len = len(stages)
                prev_stage_len = rds.get(f'{req.do_by.username}-{build_number}')
                if prev_stage_len is not None:
                    prev_stage_len = int(prev_stage_len)  # 转换为整数

                if prev_stage_len is None and stage_len > 0:
                    rds.set(f'{req.do_by.username}-{build_number}', stage_len)
                    for stage in stages:
                        helper.send_info('local', f'Jenkins任务构建中...{stage["name"]}\r\n')
                        #  输出stages的name
                if prev_stage_len is not None and stage_len == prev_stage_len:
                    continue
                else:
                    stages = stages[prev_stage_len:]
                    for stage in stages:
                        helper.send_info('local', f'Jenkins任务构建中...{stage["name"]}\r\n')
                    rds.set(f'{req.do_by.username}-{build_number}', stage_len)
    except requests.exceptions.RequestException as e:
        helper.send_error('local', f'Jenkins请求失败: {str(e)}')
        raise SpugError(f'Jenkins部署失败: {str(e)}')
    except KeyError as e:
        helper.send_error('local', f'Jenkins crumb数据解析失败: {str(e)}')
        raise SpugError(f'Jenkins部署失败: {str(e)}')


def _jenkins_log():
    print('abcd')


def _ext1_deploy(req, helper, env):
    if not req.repository_id:
        rep = Repository(
            app_id=req.deploy.app_id,
            env_id=req.deploy.env_id,
            deploy_id=req.deploy_id,
            version=req.version,
            spug_version=req.spug_version,
            extra=req.extra,
            remarks='SPUG AUTO MAKE',
            created_by_id=req.created_by_id
        )
        build_repository(rep, helper)
        req.repository = rep
    extras = json.loads(req.extra)
    if extras[0] == 'repository':
        extras = extras[1:]
    if extras[0] == 'branch':
        env.update(SPUG_GIT_BRANCH=extras[1], SPUG_GIT_COMMIT_ID=extras[2])
    else:
        env.update(SPUG_GIT_TAG=extras[1])
    if req.deploy.is_parallel:
        threads, latest_exception = [], None
        max_workers = max(10, os.cpu_count() * 5)
        with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for h_id in req.host_ids:
                new_env = AttrDict(env.items())
                t = executor.submit(_deploy_ext1_host, req, helper, h_id, new_env)
                t.h_id = h_id
                threads.append(t)
            for t in futures.as_completed(threads):
                exception = t.exception()
                if exception:
                    latest_exception = exception
                    if not isinstance(exception, SpugError):
                        helper.send_error(t.h_id, f'Exception: {exception}', False)
                else:
                    req.fail_host_ids.remove(t.h_id)
        if latest_exception:
            raise latest_exception
    else:
        host_ids = sorted(req.host_ids, reverse=True)
        while host_ids:
            h_id = host_ids.pop()
            new_env = AttrDict(env.items())
            try:
                _deploy_ext1_host(req, helper, h_id, new_env)
                req.fail_host_ids.remove(h_id)
            except Exception as e:
                helper.send_error(h_id, f'Exception: {e}', False)
                for h_id in host_ids:
                    helper.send_error(h_id, '终止发布', False)
                raise e


def _ext2_deploy(req, helper, env):
    extend, step = req.deploy.extend_obj, 1
    host_actions = json.loads(extend.host_actions)
    server_actions = json.loads(extend.server_actions)
    env.update({'SPUG_RELEASE': req.version})
    if req.version:
        for index, value in enumerate(req.version.split()):
            env.update({f'SPUG_RELEASE_{index + 1}': value})

    if not req.fail_mode:
        helper.send_info('local', f'\033[32m完成√\033[0m\r\n')
        for action in server_actions:
            helper.send_step('local', step, f'{human_time()} {action["title"]}...\r\n')
            helper.local(f'cd /tmp && {action["data"]}', env)
            step += 1

    for action in host_actions:
        if action.get('type') == 'transfer':
            action['src'] = render_str(action.get('src', '').strip().rstrip('/'), env)
            action['dst'] = render_str(action['dst'].strip().rstrip('/'), env)
            if action.get('src_mode') == '1':  # upload when publish
                extra = json.loads(req.extra)
                if 'name' in extra:
                    action['name'] = extra['name']
                break
            helper.send_step('local', step, f'{human_time()} 检测到来源为本地路径的数据传输动作，执行打包...   \r\n')
            action['src'] = action['src'].rstrip('/ ')
            action['dst'] = action['dst'].rstrip('/ ')
            if not action['src'] or not action['dst']:
                helper.send_error('local', f'Invalid path for transfer, src: {action["src"]} dst: {action["dst"]}')
            if not os.path.exists(action['src']):
                helper.send_error('local', f'No such file or directory: {action["src"]}')
            is_dir, exclude = os.path.isdir(action['src']), ''
            sp_dir, sd_dst = os.path.split(action['src'])
            contain = sd_dst
            if action['mode'] != '0' and is_dir:
                files = helper.parse_filter_rule(action['rule'], ',', env)
                if files:
                    if action['mode'] == '1':
                        contain = ' '.join(f'{sd_dst}/{x}' for x in files)
                    else:
                        excludes = []
                        for x in files:
                            if x.startswith('/'):
                                excludes.append(f'--exclude={sd_dst}{x}')
                            else:
                                excludes.append(f'--exclude={x}')
                        exclude = ' '.join(excludes)
            tar_gz_file = f'{req.spug_version}.tar.gz'
            helper.local(f'cd {sp_dir} && tar -zcf {tar_gz_file} {exclude} {contain}')
            helper.send_info('local', f'{human_time()} \033[32m完成√\033[0m\r\n')
            helper.add_callback(partial(os.remove, os.path.join(sp_dir, tar_gz_file)))
            break
    helper.send_step('local', 100, '')

    if host_actions:
        if req.deploy.is_parallel:
            threads, latest_exception = [], None
            max_workers = max(10, os.cpu_count() * 5)
            with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                for h_id in req.host_ids:
                    new_env = AttrDict(env.items())
                    t = executor.submit(_deploy_ext2_host, helper, h_id, host_actions, new_env, req.spug_version)
                    t.h_id = h_id
                    threads.append(t)
                for t in futures.as_completed(threads):
                    exception = t.exception()
                    if exception:
                        latest_exception = exception
                        if not isinstance(exception, SpugError):
                            helper.send_error(t.h_id, f'Exception: {exception}', False)
                    else:
                        req.fail_host_ids.remove(t.h_id)
            if latest_exception:
                raise latest_exception
        else:
            host_ids = sorted(req.host_ids, reverse=True)
            while host_ids:
                h_id = host_ids.pop()
                new_env = AttrDict(env.items())
                try:
                    _deploy_ext2_host(helper, h_id, host_actions, new_env, req.spug_version)
                    req.fail_host_ids.remove(h_id)
                except Exception as e:
                    helper.send_error(h_id, f'Exception: {e}', False)
                    for h_id in host_ids:
                        helper.send_error(h_id, '终止发布', False)
                    raise e
    else:
        req.fail_host_ids = []
        helper.send_step('local', 100, f'\r\n{human_time()} ** 发布成功 **')


def _deploy_ext1_host(req, helper, h_id, env):
    helper.send_step(h_id, 1, f'\033[32m就绪√\033[0m\r\n{human_time()} 数据准备...        ')
    host = Host.objects.filter(pk=h_id).first()
    if not host:
        helper.send_error(h_id, 'no such host')
    env.update({'SPUG_HOST_ID': h_id, 'SPUG_HOST_NAME': host.hostname})
    extend = req.deploy.extend_obj
    extend.dst_dir = render_str(extend.dst_dir, env)
    extend.dst_repo = render_str(extend.dst_repo, env)
    env.update(SPUG_DST_DIR=extend.dst_dir)
    with host.get_ssh(default_env=env) as ssh:
        base_dst_dir = os.path.dirname(extend.dst_dir)
        code, _ = ssh.exec_command_raw(
            f'mkdir -p {extend.dst_repo} {base_dst_dir} && [ -e {extend.dst_dir} ] && [ ! -L {extend.dst_dir} ]')
        if code == 0:
            helper.send_error(host.id,
                              f'检测到该主机的发布目录 {extend.dst_dir!r} 已存在，为了数据安全请自行备份后删除该目录，Spug 将会创建并接管该目录。')
        if req.type == '2':
            helper.send_step(h_id, 1, '\033[33m跳过√\033[0m\r\n')
        else:
            # clean
            clean_command = f'ls -d {extend.deploy_id}_* 2> /dev/null | sort -t _ -rnk2 | tail -n +{extend.versions + 1} | xargs rm -rf'
            helper.remote_raw(host.id, ssh, f'cd {extend.dst_repo} && {clean_command}')
            # transfer files
            tar_gz_file = f'{req.spug_version}.tar.gz'
            try:
                callback = helper.progress_callback(host.id)
                ssh.put_file(
                    os.path.join(BUILD_DIR, tar_gz_file),
                    os.path.join(extend.dst_repo, tar_gz_file),
                    callback
                )
            except Exception as e:
                helper.send_error(host.id, f'Exception: {e}')

            command = f'cd {extend.dst_repo} && rm -rf {req.spug_version} && tar xf {tar_gz_file} && rm -f {req.deploy_id}_*.tar.gz'
            helper.remote_raw(host.id, ssh, command)
            helper.send_step(h_id, 1, '\033[32m完成√\033[0m\r\n')

        # pre host
        repo_dir = os.path.join(extend.dst_repo, req.spug_version)
        if extend.hook_pre_host:
            helper.send_step(h_id, 2, f'{human_time()} 发布前任务...       \r\n')
            command = f'cd {repo_dir} && {extend.hook_pre_host}'
            helper.remote(host.id, ssh, command)

        # do deploy
        helper.send_step(h_id, 3, f'{human_time()} 执行发布...        ')
        helper.remote_raw(host.id, ssh, f'rm -f {extend.dst_dir} && ln -sfn {repo_dir} {extend.dst_dir}')
        helper.send_step(h_id, 3, '\033[32m完成√\033[0m\r\n')

        # post host
        if extend.hook_post_host:
            helper.send_step(h_id, 4, f'{human_time()} 发布后任务...       \r\n')
            command = f'cd {extend.dst_dir} && {extend.hook_post_host}'
            helper.remote(host.id, ssh, command)

        helper.send_step(h_id, 100, f'\r\n{human_time()} ** \033[32m发布成功\033[0m **')


def _deploy_ext2_host(helper, h_id, actions, env, spug_version):
    helper.send_info(h_id, '\033[32m就绪√\033[0m\r\n')
    host = Host.objects.filter(pk=h_id).first()
    if not host:
        helper.send_error(h_id, 'no such host')
    env.update({'SPUG_HOST_ID': h_id, 'SPUG_HOST_NAME': host.hostname})
    with host.get_ssh(default_env=env) as ssh:
        for index, action in enumerate(actions):
            helper.send_step(h_id, 1 + index, f'{human_time()} {action["title"]}...\r\n')
            if action.get('type') == 'transfer':
                if action.get('src_mode') == '1':
                    try:
                        dst = action['dst']
                        command = f'[ -e {dst} ] || mkdir -p $(dirname {dst}); [ -d {dst} ]'
                        code, _ = ssh.exec_command_raw(command)
                        if code == 0:  # is dir
                            if not action.get('name'):
                                raise RuntimeError('internal error 1002')
                            dst = dst.rstrip('/') + '/' + action['name']
                        callback = helper.progress_callback(host.id)
                        ssh.put_file(os.path.join(REPOS_DIR, env.SPUG_DEPLOY_ID, spug_version), dst, callback)
                    except Exception as e:
                        helper.send_error(host.id, f'Exception: {e}')
                    helper.send_info(host.id, 'transfer completed\r\n')
                    continue
                else:
                    sp_dir, sd_dst = os.path.split(action['src'])
                    tar_gz_file = f'{spug_version}.tar.gz'
                    try:
                        callback = helper.progress_callback(host.id)
                        ssh.put_file(os.path.join(sp_dir, tar_gz_file), f'/tmp/{tar_gz_file}', callback)
                    except Exception as e:
                        helper.send_error(host.id, f'Exception: {e}')

                    command = f'mkdir -p /tmp/{spug_version} && tar xf /tmp/{tar_gz_file} -C /tmp/{spug_version}/ '
                    command += f'&& rm -rf {action["dst"]} && mv /tmp/{spug_version}/{sd_dst} {action["dst"]} '
                    command += f'&& rm -rf /tmp/{spug_version}* && echo "transfer completed"'
            else:
                command = f'cd /tmp && {action["data"]}'
            helper.remote(host.id, ssh, command)

    helper.send_step(h_id, 100, f'\r\n{human_time()} ** \033[32m发布成功\033[0m **')
