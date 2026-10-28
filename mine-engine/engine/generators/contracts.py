"""ArtifactGenerator：加载种子合约作为注入漏洞基准体。"""

from pathlib import Path

from ..core.pipeline import ArtifactGenerator


class ContractGenerator(ArtifactGenerator):
    name = "contract-generator"

    def __init__(self, src_dir, **config):
        super().__init__(**config)
        self.src_dir = Path(src_dir)

    def run(self, records):
        out = []
        for rec in records:
            rel = rec["clean_rel_path"]
            path = self.src_dir / rel
            source = path.read_text(encoding="utf-8")
            out.append(
                {
                    **rec,
                    "clean_path": str(path),
                    "clean_source": source,
                }
            )
        return out
