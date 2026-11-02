import os
from jobmvp import cli, registry
from tests.test_pipeline import Fake, J
from tests.conftest import DSN

def test_cli_run_exit_codes(conn, monkeypatch, tmp_path):
    monkeypatch.setenv("JOBMVP_DSN", DSN)
    assert cli.main(["run", "fx"]) == 2                                   # 未注册适配器
    registry.REGISTRY["fx"] = lambda: Fake([[J(1)]])
    # raw 默认落 ./data/raw；用 tmp_path 而不是硬编码 /tmp（Windows 下 /tmp 不可写）
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", "fx"]) == 0
    conn.execute("UPDATE source_config SET enabled=false"); conn.commit()
    assert cli.main(["run", "fx"]) == 3                                   # 禁用源不发请求
    assert cli.main(["reap"]) == 0
