/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Steps } from 'antd';
import styles from './index.module.css';
import Ext3Setup1 from './Ext3Setup1';
import store from './store';

export default observer(function Ext3Form() {
  const appName = store.currentRecord.name;
  let title = `Jenkins发布 - ${appName}`;
  if (store.deploy.id) {
    store.isReadOnly ? title = '查看' + title : title = '编辑' + title;
  } else {
    title = '新建' + title
  }
  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={title}
      onCancel={() => store.ext3Visible = false}
      footer={null}>
      <Steps current={store.page} className={styles.steps}>
        <Steps.Step key={0} title="Jenkins配置"/>
      </Steps>
      {store.page === 0 && <Ext3Setup1/>}
    </Modal>
  )
})
