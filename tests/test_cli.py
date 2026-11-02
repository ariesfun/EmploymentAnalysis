import os
from pathlib import Path
from jobmvp import cli, registry
from tests.test_pipeline import Fake, J
from tests.conftest import DSN

def test_cli_run_exit_codes(conn, monkeypatch):
    monkeypatch.setenv("JOBMVP_DSN", DSN)
    assert cli.main(["run", "fx"]) == 2                                   # 未注册适配器
    registry.REGISTRY["fx"] = lambda: Fake([[J(1)]])
    # raw 默认落 ./data/raw，需要一个可写的 cwd。
    # 不用 pytest 的 tmp_path：它在会话结束时走 shutil.rmtree，会被宿主的删除守卫拦下
    # 并 SystemExit(1)，导致"全部用例通过但退出码是 1、且不打印汇总"（踩过）。
    workdir = Path(__file__).resolve().parent.parent / ".tmp" / "cli-test"
    workdir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(workdir)
    assert cli.main(["run", "fx"]) == 0
    conn.execute("UPDATE source_config SET enabled=false"); conn.commit()
    assert cli.main(["run", "fx"]) == 3                                   # 禁用源不发请求
    assert cli.main(["reap"]) == 0
