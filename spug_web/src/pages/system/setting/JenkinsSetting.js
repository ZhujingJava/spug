/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Form, Button, Input, Space, message } from 'antd';
import styles from './index.module.css';
import { http } from 'libs';
import store from './store';

export default observer(function JenkinsSetting() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  function handleSubmit() {
    store.loading = true;
    const formData = form.getFieldsValue();
    http.post('/api/setting/', {data: [{key: 'jenkins_config', value: formData}]})
      .then(() => {
        message.success('保存成功');
        store.fetchSettings()
      })
      .finally(() => store.loading = false)
  }

  function jenkinsTest() {
    setLoading(true);
    const formData = form.getFieldsValue();
    http.post('/api/setting/jenkins_test/', formData)
      .then(() => {
        message.success('Jenkins服务连接成功')
      })
      .finally(() => setLoading(false))
  }

  return (
    <React.Fragment>
      <div className={styles.title}>Jenkins配置</div>
      <Form
        form={form}
        initialValues={store.settings.jenkins_config}
        style={{maxWidth: 500}}
        labelCol={{span: 8}}
        wrapperCol={{span: 16}}
      >
        <Form.Item required name="url" label="Jenkins地址" extra="Jenkins服务器的访问地址">
          <Input placeholder="例如：http://jenkins.example.com"/>
        </Form.Item>
        <Form.Item name="username" label="用户名" extra="Jenkins访问用户名（可选）">
          <Input placeholder="请输入Jenkins用户名"/>
        </Form.Item>
        <Form.Item name="token" label="API Token" extra="Jenkins API Token（可选）">
          <Input.Password placeholder="请输入Jenkins API Token"/>
        </Form.Item>
        <Space style={{marginTop: 24}}>
          <Button type="danger" loading={loading} onClick={jenkinsTest}>测试连接</Button>
          <Button type="primary" loading={store.loading} onClick={handleSubmit}>保存设置</Button>
        </Space>
      </Form>
    </React.Fragment>
  )
})
