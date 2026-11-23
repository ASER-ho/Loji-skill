"""Validate DSH Cordis patch as data without evaluating !!js expressions."""
from pathlib import Path
import re
import yaml

ROOT=Path(__file__).resolve().parents[2]
class DSHLoader(yaml.SafeLoader):
    pass
DSHLoader.add_constructor("tag:yaml.org,2002:js",lambda loader,node: loader.construct_scalar(node))
patch=(ROOT/"loji-dsh/cordis.patch.yml").read_text(encoding="utf-8")
document=yaml.load(patch,Loader=DSHLoader)
assert isinstance(document,list) and len(document)==1, "expected one insert patch"
rows=document[0]["insert"]
assert len(rows)==2, "expected provider and preset"
assert rows[0]["id"]=="loji-skill" and rows[0]["name"]=="loji-dsh"
preset=rows[1]
assert preset["id"]=="preset-loji" and preset["name"]=="@deepseek-ai/dsh-agent-preset"
config=preset["config"]
assert config["id"]=="loji" and config["name"]=="长征机/逻辑" and config["order"]==2
plugins=config["plugins"]
assert len(plugins)==22, f"expected 22 top-level plugins: {len(plugins)}"
assert len({p["id"] for p in plugins})==len(plugins)
assert plugins[0]["id"]=="persona" and plugins[0]["name"]=="@deepseek-ai/dsh-persona"
source=(ROOT/"SKILL.md").read_text(encoding="utf-8")
expected="你正在使用「长征机/逻辑」角色模式（Loji，亦称征酱）。角色设定是虚构模拟，不是真实自主意识。严守宿主安全规则和用户的实际权限；不声称已执行未执行的操作。\n\n"+source[source.index("## 角色身份"):source.index("### 三、心智模型")].rstrip()
assert plugins[0]["config"]["prefix"]==expected, "persona must match canonical skill"
print("DSH preset validation OK: provider + preset, 22 plugins, persona matches source")
