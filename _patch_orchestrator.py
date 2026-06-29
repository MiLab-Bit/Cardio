"""Patch orchestrator.py: add YAML loading + DAG executor support."""
import sys

TARGET = "byou/core/orchestrator.py"

with open(TARGET, encoding="utf-8") as f:
    content = f.read()

# ── 3. Replace the `stages` property ──────────────────────
old_property = '''    @property
    def stages(self) -> list[Stage]:
        \"\"\"Return the stage list (subclass hook + default).\"\"\"
        if self._stages is not None:
            return self._stages
        return DEFAULT_STAGES'''

new_property = '''    @property
    def stages(self) -> list[Stage]:
        \"\"\"Return the stage list (YAML config > subclass hook > default).\"\"\"
        if self._stages is not None:
            return self._stages
        if self.pipeline_config_path:
            try:
                self._stages = self._load_stages_from_yaml(self.pipeline_config_path)
                logger.info(
                    "Loaded %d stages from %s",
                    len(self._stages), self.pipeline_config_path,
                )
                return self._stages
            except Exception as exc:
                logger.warning(
                    "Failed to load pipeline config from %s: %s",
                    self.pipeline_config_path, exc,
                )
        return DEFAULT_STAGES'''

if old_property in content:
    content = content.replace(old_property, new_property, 1)
    print("[OK] Replaced stages property")
else:
    print("[WARN] stages property not found — may already be patched")

# ── 4. Add _load_stages_from_yaml static method ───────────
# Insert before the `_run_stages` method
loader_method = '''

    # ── YAML config loader ────────────────────────────────────

    @staticmethod
    def _load_stages_from_yaml(path: str) -> list[Stage]:
        \"\"\"Load pipeline stages from a YAML config file.\"\"\"
        import yaml
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        stage_ids = []
        stages = []
        for s_cfg in cfg.get("stages", []):
            sid = s_cfg["id"]
            stage_ids.append(sid)
            stages.append(Stage(
                key=sid,
                agent_key=s_cfg["agent_key"],
                label_start=s_cfg.get("label_start", sid),
                label_done=s_cfg.get("label_done", sid + "_done"),
                required=s_cfg.get("required", True),
                deps=s_cfg.get("deps", []),
                timeout=s_cfg.get("timeout", 30),
                retry=s_cfg.get("retry", 2),
            ))
        return stages

'''

insert_before = "    # ── Stage execution loop ─"
if insert_before in content and "_load_stages_from_yaml" not in content:
    content = content.replace(insert_before, loader_method + insert_before, 1)
    print("[OK] Added _load_stages_from_yaml loader")
else:
    print("[INFO] Loader already present or insert point not found")

# ── 5. Replace _run_stages body with DAG executor ─────────
old_run = '''    async def _run_stages(
        self,
        ctx: PipelineContext,
        card_path: str | None,
        audio_path: str | None,
        skip: set[str],
        on_progress: Callable[[str, dict], None] | None,
    ) -> None:
        \"\"\"Declarative stage loop — the heart of the pipeline.\"\"\"
        for stage in self.stages:
            if stage.key in skip or stage.agent_key in skip:
                logger.debug("Stage skipped: %s", stage.key)
                continue

            await self._emit(on_progress, stage.label_start, {})

            agent = self._agents.get(stage.agent_key)
            if agent is None:
                if stage.required:
                    raise RuntimeError(
                        f"Required agent '{stage.agent_key}' (stage '{stage.key}') "
                        "is not registered. Call orch.register_agent() first."
                    )
                logger.debug("Optional agent '%s' not registered — skipping stage '%s'.",
                             stage.agent_key, stage.key)
                continue

            input_data = stage.input_builder(ctx, card_path, audio_path)
            result = await agent.execute(input_data)
            stage.output_handler(ctx, result)

            await self._emit(on_progress, stage.label_done, result)'''

new_run = '''    async def _run_stages(
        self,
        ctx: PipelineContext,
        card_path: str | None,
        audio_path: str | None,
        skip: set[str],
        on_progress: Callable[[str, dict], None] | None,
    ) -> None:
        \"\"\"Execute stages via DAG executor (parallel when deps allow).\"\"\"
        executor = PipelineDAGExecutor(
            stages=self.stages,
            max_concurrent=self._settings.max_concurrent_pipelines,
        )
        await executor.execute(
            ctx=ctx,
            orchestrator=self,
            card_path=card_path,
            audio_path=audio_path,
            on_progress=on_progress,
            skip_stages=skip,
        )'''

if old_run in content:
    content = content.replace(old_run, new_run, 1)
    print("[OK] Replaced _run_stages with DAG executor")
else:
    print("[WARN] _run_stages not found — checking if already patched...")
    if "PipelineDAGExecutor" in content:
        print("  [INFO] DAG executor reference found — may already be patched")
    else:
        # Try to find the method and show context
        lines = content.split("\\n")
        for i, line in enumerate(lines):
            if "_run_stages" in line:
                print(f"  Found at line {i+1}: {line}")
                break

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(content)

print("\\nDone. Validate with: python -c 'import ast; ast.parse(open(\\'byou/core/orchestrator.py\').read())'\" )
