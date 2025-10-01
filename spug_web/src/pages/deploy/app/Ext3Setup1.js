/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Button, Form, Input, message, Select} from 'antd';
import {http} from 'libs';
import store from './store';
import envStore from "../../config/environment/store";
import {Link} from "react-router-dom";

export default observer(function Ext3Setup1() {
    const [envs, setEnvs] = useState([]);
    const [loading, setLoading] = useState(false);
    const [visible, setVisible] = useState(false);

    function updateEnvs() {
        const ids = store.currentRecord['deploys'].map(x => x.env_id);
        setEnvs(ids.filter(x => x !== store.deploy.env_id))
    }

    useEffect(() => {
        if (!info.host_ids) {
            info.host_ids = []; // 为 Jenkins 发布类型设置默认空数组
        }
        if (store.currentRecord['deploys'] === undefined) {
            store.loadDeploys(store.app_id).then(updateEnvs)
        } else {
            updateEnvs()
        }
    }, [])

    const info = store.deploy;

    function handleSubmit() {
        setLoading(true);
        const formData = {...info};
        formData['app_id'] = store.app_id;
        formData['extend'] = '3';


        http.post('/api/app/deploy/', formData)
            .then(res => {
                message.success('保存成功');
                store.ext3Visible = false;
                store.loadDeploys(store.app_id)
            })
            .finally(() => setLoading(false))
    }

    return (

        <Form labelCol={{span: 6}} wrapperCol={{span: 14}}>
            <Form.Item required label="发布环境" style={{marginBottom: 0}}
                       tooltip="可以建立多个环境，实现同一应用在不同环境里配置不同的发布流程。">
                <Form.Item style={{display: 'inline-block', width: '80%'}}>
                    <Select disabled={store.isReadOnly} value={info.env_id} onChange={v => info.env_id = v}
                            placeholder="请选择发布环境">
                        {envStore.records.map(item => (
                            <Select.Option disabled={envs.includes(item.id)} value={item.id}
                                           key={item.id}>{item.name}</Select.Option>
                        ))}
                    </Select>
                </Form.Item>
                <Form.Item style={{display: 'inline-block', width: '20%', textAlign: 'right'}}>
                    <Link disabled={store.isReadOnly} to="/config/environment">新建环境</Link>
                </Form.Item>
            </Form.Item>
            {/*<Form.Item required label="Git仓库地址">*/}
            {/*    <Input*/}
            {/*        disabled={store.isReadOnly}*/}
            {/*        value={info.git_repo}*/}
            {/*        onChange={e => info.git_repo = e.target.value}*/}
            {/*        placeholder="请输入Git仓库地址"/>*/}
            {/*</Form.Item>*/}
            <Form.Item required label="Git仓库地址">
                <Input disabled={store.isReadOnly} value={info['git_repo']}
                       onChange={e => info['git_repo'] = e.target.value}
                       placeholder="请输入Git仓库地址"/>
            </Form.Item>
            <Form.Item required label="Jenkins任务名称">
                <Input
                    disabled={store.isReadOnly}
                    value={info.job_name}
                    onChange={e => info.job_name = e.target.value}
                    placeholder="请输入Jenkins任务名称"/>
            </Form.Item>

            <Form.Item wrapperCol={{span: 14, offset: 6}}>
                <Button
                    type="primary"
                    loading={loading}
                    disabled={!(info.git_repo && info.job_name)}
                    onClick={handleSubmit}>
                    提交
                </Button>
            </Form.Item>
        </Form>

    )
})
