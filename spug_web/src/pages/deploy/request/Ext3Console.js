/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useEffect, useState} from 'react';
import {observer, useLocalStore} from 'mobx-react';
import {Alert, Card, Collapse, Modal, Progress, Skeleton, Steps} from 'antd';
import {CloseOutlined, LoadingOutlined, ShrinkOutlined} from '@ant-design/icons';
import OutView from './OutView';
import {http, X_TOKEN} from 'libs';
import styles from './index.module.less';
import store from './store';

function Ext3Console(props) {
    const outputs = useLocalStore(() => ({local: {data: ''}}));
    const terms = useLocalStore(() => ({}));
    const [mini, setMini] = useState(false);
    const [visible, setVisible] = useState(true);
    const [fetching, setFetching] = useState(true);
    const [buildInfo, setBuildInfo] = useState({});
    const [buildNumber, setBuildNumber] = useState(null);
    const [jenkinsWs, setJenkinsWs] = useState(null);

    useEffect(props.request.mode === 'read' ? readDeploy : doDeploy, [])


    function readDeploy() {
        let socket;
        http.get(`/api/deploy/request/${props.request.id}/`)
            .then(res => {
                Object.assign(outputs, res.outputs)
                setBuildInfo(res.build_info || {})
                setTimeout(() => setFetching(false), 100)
                if (res.status === '2') {
                    socket = _makeSocket(res.index)
                }
            })
        return () => socket && socket.close()
    }

    function doDeploy() {
        // 通过id获取request信息
        const git_branch = props.request.extra[1];
        const deploy_id = props.request.deploy_id;
        const commit_id = props.request.extra[2];

// 修改为通过后端API代理请求Jenkins


        let socket;
        http.post(`/api/deploy/request/${props.request.id}/`, {mode: props.request.mode})
            .then(res => {
                console.log('outputs', res.outputs)
                Object.assign(outputs, res.outputs)
                setBuildInfo(res.build_info || {})
                setTimeout(() => setFetching(false), 100)
                socket = _makeSocket()
                store.fetchInfo(props.request.id)
            })
        return () => socket && socket.close()
    }

    function _makeSocket(index = 0) {
        const token = props.request.id;
        console.log('request.id',token)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/request/${token}/?x-token=${X_TOKEN}`);
        socket.onopen = () => socket.send(String(index));
        socket.onmessage = e => {
            if (e.data === 'pong') {
                socket.send(String(index))
            } else {
                index += 1;
                const {key, data, step, status, build_info} = JSON.parse(e.data);
                if (!outputs[key]) return
                if (data !== undefined) {
                    outputs[key].data += data
                    if (terms[key]) terms[key].write(data)
                }
                if (step !== undefined) outputs[key].step = step;
                if (status !== undefined) outputs[key].status = status;
                if (build_info !== undefined) setBuildInfo(build_info);
            }
        }
        socket.onerror = () => {
            outputs.jenkins['status'] = 'error'
            outputs.jenkins.data = '\u001b[31mWebsocket connection failed!\u001b[0m'
            if (terms.jenkins) {
                terms.jenkins.reset()
                terms.jenkins.write('\u001b[31mWebsocket connection failed!\u001b[0m')
            }
        }
        return socket
    }

    function switchMiniMode() {
        setMini(true)
        setVisible(false)
    }

    function handleSetTerm(term, key) {
        if (outputs[key] && outputs[key].data) {
            term.write(outputs[key].data)
        }
        terms[key] = term
    }

    function StepItem(props) {
        let icon = null;
        if (props.step === props.item.step && props.item.status !== 'error') {
            icon = <LoadingOutlined/>
        }
        return <Steps.Step {...props} icon={icon}/>
    }

    const jenkinsSteps = [
        {title: "触发Jenkins任务", step: 0},
        {title: "Jenkins构建中", step: 1},
        {title: "构建完成", step: 2}
    ];

    return (
        <div>
            {mini && (
                <Card
                    className={styles.item}
                    bodyStyle={{padding: '8px 12px'}}
                    onClick={() => setVisible(true)}>
                    <div className={styles.header}>
                        <div className={styles.title}>{props.request.name}</div>
                        <CloseOutlined onClick={() => store.showConsole(props.request, true)}/>
                    </div>
                    <Progress
                        percent={buildInfo.progress || 0}
                        status={buildInfo.status === 'SUCCESS' ? 'success' : buildInfo.status === 'FAILURE' ? 'exception' : 'active'}/>
                </Card>
            )}
            <Modal
                visible={visible}
                width="70%"
                footer={null}
                maskClosable={false}
                className={styles.console}
                onCancel={() => store.showConsole(props.request, true)}
                title={[
                    <span key="1">{props.request.name}</span>,
                    <div key="2" className={styles.miniIcon} onClick={switchMiniMode}>
                        <ShrinkOutlined/>
                    </div>
                ]}>
                <Skeleton loading={fetching} active>
                    <Collapse defaultActiveKey={['0']} className={styles.collapse}>
                        <Collapse.Panel header={(
                            <div className={styles.header}>
                                <b className={styles.title}>Jenkins构建信息</b>
                                <Steps size="small" className={styles.step} current={buildInfo.step || 0}
                                       status={buildInfo.status}>
                                    {jenkinsSteps.map((step, index) => (
                                        <StepItem key={index} title={step.title} item={buildInfo} step={step.step}/>
                                    ))}
                                </Steps>
                            </div>
                        )}>
                            {buildInfo.url && (
                                <Alert
                                    message={`Jenkins任务: ${buildInfo.url}`}
                                    type="info"
                                    showIcon
                                    style={{marginBottom: 12}}
                                />
                            )}
                            <OutView setTerm={term => handleSetTerm(term, 'local')}/>
                        </Collapse.Panel>
                    </Collapse>
                </Skeleton>
            </Modal>
        </div>
    )

}

export default observer(Ext3Console)