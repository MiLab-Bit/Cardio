import importlib, sys

modules = [
    'byou.agents', 'byou.agents.base', 'byou.agents.configs',
    'byou.core.orchestrator', 'byou.core.runtime', 'byou.core.message_bus',
    'byou.core.learning_loop', 'byou.core.llm_client', 'byou.core.llm_parser',
    'byou.cua.perception', 'byou.cua.planning', 'byou.cua.execution',
    'byou.models', 'byou.models.customer',
    'byou.config.settings',
    'byou.tools.search', 'byou.tools.ocr', 'byou.tools.crm', 'byou.tools.asr',
    'byou.infrastructure.browser', 'byou.infrastructure.cache',
    'byou.api', 'byou.cli',
]

errors = []
for mod in modules:
    try:
        importlib.import_module(mod)
        print(f'  OK: {mod}')
    except Exception as e:
        print(f'  FAIL: {mod} -> {e}')
        errors.append(mod)

print('---')
print(f'{len(errors)} errors' if errors else 'All modules OK')
