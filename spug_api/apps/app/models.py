# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from django.conf import settings
from libs import ModelMixin, human_datetime
from apps.account.models import User
from apps.config.models import Environment
import subprocess
import json
import os


class App(models.Model, ModelMixin):
    name = models.CharField(max_length=50)
    key = models.CharField(max_length=50, unique=True)
    desc = models.CharField(max_length=255, null=True)
    rel_apps = models.TextField(null=True)
    rel_services = models.TextField(null=True)
    sort_id = models.IntegerField(default=0, db_index=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)

    def to_dict(self, *args, **kwargs):
        tmp = super().to_dict(*args, **kwargs)
        tmp['rel_apps'] = json.loads(self.rel_apps) if self.rel_apps else []
        tmp['rel_services'] = json.loads(self.rel_services) if self.rel_services else []
        return tmp

    def __repr__(self):
        return f'<App {self.name!r}>'

    class Meta:
        db_table = 'apps'
        ordering = ('-sort_id',)


class Deploy(models.Model, ModelMixin):
    EXTENDS = (
        ('1', '常规发布'),
        ('2', '自定义发布'),
        ('3', 'Jenkins发布'),
    )
    app = models.ForeignKey(App, on_delete=models.PROTECT)
    env = models.ForeignKey(Environment, on_delete=models.PROTECT)
    host_ids = models.TextField()
    extend = models.CharField(max_length=2, choices=EXTENDS)
    is_audit = models.BooleanField()
    is_parallel = models.BooleanField(default=True)
    rst_notify = models.CharField(max_length=255, null=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    @property
    def extend_obj(self):
        if self.extend == '1':
            cls = DeployExtend1
        elif self.extend == '2':
            cls = DeployExtend2
        elif self.extend == '3':
            cls = DeployExtend3
        else:
            return None
        return cls.objects.filter(deploy=self).first()

    def to_dict(self, *args, **kwargs):
        deploy = super().to_dict(*args, **kwargs)
        deploy['app_key'] = self.app_key if hasattr(self, 'app_key') else None
        deploy['app_name'] = self.app_name if hasattr(self, 'app_name') else None
        deploy['host_ids'] = json.loads(self.host_ids)
        deploy['rst_notify'] = json.loads(self.rst_notify)
        deploy.update(self.extend_obj.to_dict())
        return deploy

    def delete(self, using=None, keep_parents=False):
        deploy_id = self.id
        super().delete(using, keep_parents)
        repo_dir = os.path.join(settings.REPOS_DIR, str(deploy_id))
        build_dir = os.path.join(settings.BUILD_DIR, f'{deploy_id}_*')
        subprocess.Popen(f'rm -rf {repo_dir} {repo_dir + "_*"} {build_dir}', shell=True)

    def __repr__(self):
        return '<Deploy app_id=%r env_id=%r>' % (self.app_id, self.env_id)

    class Meta:
        db_table = 'deploys'
        ordering = ('-id',)


class DeployExtend1(models.Model, ModelMixin):
    deploy = models.OneToOneField(Deploy, primary_key=True, on_delete=models.CASCADE)
    git_repo = models.CharField(max_length=255)
    dst_dir = models.CharField(max_length=255)
    dst_repo = models.CharField(max_length=255)
    versions = models.IntegerField()
    filter_rule = models.TextField()
    hook_pre_server = models.TextField(null=True)
    hook_post_server = models.TextField(null=True)
    hook_pre_host = models.TextField(null=True)
    hook_post_host = models.TextField(null=True)

    def to_dict(self, *args, **kwargs):
        tmp = super().to_dict(*args, **kwargs)
        tmp['filter_rule'] = json.loads(self.filter_rule)
        return tmp

    def __repr__(self):
        return '<DeployExtend1 deploy_id=%r>' % self.deploy_id

    class Meta:
        db_table = 'deploy_extend1'


class DeployExtend2(models.Model, ModelMixin):
    deploy = models.OneToOneField(Deploy, primary_key=True, on_delete=models.CASCADE)
    server_actions = models.TextField()
    host_actions = models.TextField()
    require_upload = models.BooleanField(default=False)

    def to_dict(self, *args, **kwargs):
        tmp = super().to_dict(*args, **kwargs)
        tmp['server_actions'] = json.loads(self.server_actions)
        tmp['host_actions'] = json.loads(self.host_actions)
        return tmp

    def __repr__(self):
        return '<DeployExtend2 deploy_id=%r>' % self.deploy_id

    class Meta:
        db_table = 'deploy_extend2'



class DeployExtend3(models.Model, ModelMixin):
    # 与主表的关联关系 (必需)
    deploy = models.OneToOneField(Deploy, primary_key=True, on_delete=models.CASCADE)

    # Jenkins Job 的名称 (必需)
    # 这是告诉 Spug 要触发 Jenkins 上的哪一个任务
    job_name = models.CharField(max_length=255, help_text="Jenkins Job 的完整路径名称，例如 'WebApp/build-frontend'")


    git_repo = models.CharField(max_length=255,null=True,  help_text="Jenkins Job 所依赖的 Git 仓库")
    # 参数化构建 (强烈建议保留)
    # 不同的发布配置，需要传递给 Jenkins 的参数通常是不同的
    job_params = models.TextField(null=True, blank=True, help_text="传递给Jenkins的自定义参数，JSON格式的键值对")

    def to_dict(self, *args, **kwargs):
        tmp = super().to_dict(*args, **kwargs)
        if self.job_params:
            try:
                tmp['job_params'] = json.loads(self.job_params)
            except (json.JSONDecodeError, TypeError):
                tmp['job_params'] = {}
        else:
            tmp['job_params'] = {}
        return tmp

    def __repr__(self):
        return f'<DeployExtend3 deploy_id={self.deploy_id}>'

    class Meta:
        db_table = 'deploy_extend3'