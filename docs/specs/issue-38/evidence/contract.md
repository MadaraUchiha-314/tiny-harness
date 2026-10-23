# T3 — contract tests

Work item issue-38, activity T3. Schemas, the agent card and public-API snapshots.

2026-10-22, branch `issue-38-multimodal` at `ec5f6b8`, Python 3.14.7.

## `uv run pytest tests/contract -v`

```text
tests/contract/test_agent_card.py::test_agent_card_snapshot PASSED      
tests/contract/test_agent_card.py::test_the_card_is_unchanged_without_media PASSED
tests/contract/test_agent_card.py::test_agent_card_with_media_snapshot PASSED
tests/contract/test_channel_extension_schema.py::test_channel_extension_schema_matches_the_committed_file PASSED
tests/contract/test_channel_extension_schema.py::test_channels_and_persistence_api_snapshots PASSED
tests/contract/test_commands_api.py::test_commands_api_snapshot PASSED  
tests/contract/test_config_api.py::test_config_api_snapshot PASSED      
tests/contract/test_config_api.py::test_settings_json_schema_snapshot PASSED
tests/contract/test_entities_api.py::test_entities_api_snapshot PASSED  
tests/contract/test_errors_api.py::test_errors_api_snapshot PASSED      
tests/contract/test_ext_schemas.py::test_status_schema_documents_both_sub_states_without_a_closed_enum PASSED
tests/contract/test_ext_schemas.py::test_commands_schema_is_the_card_params_model PASSED
tests/contract/test_ext_schemas.py::test_the_card_advertises_status_and_the_registered_commands PASSED
tests/contract/test_ext_schemas.py::test_media_schema_documents_the_params_and_the_metadata PASSED
tests/contract/test_fastapi_api.py::test_fastapi_api_snapshot PASSED    
tests/contract/test_home_api.py::test_home_api_snapshot PASSED          
tests/contract/test_hooks_api.py::test_hooks_api_snapshot PASSED        
tests/contract/test_interaction_api.py::test_renderer_api_snapshot PASSED
tests/contract/test_interaction_api.py::test_surface_api_snapshot PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[create_plan] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[complete_step] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[spawn_subtask] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[ask_participant] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[create_task_for_participant] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[set_participant_role] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[list_skills] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[load_skill] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[unload_skill] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[list_skill_resources] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[load_skill_resource] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[emit_ui] PASSED
tests/contract/test_intrinsic_schemas.py::test_intrinsic_schema_matches_the_committed_file[generate_image] PASSED
tests/contract/test_intrinsic_schemas.py::test_every_intrinsic_is_an_intrinsic_with_a_strict_schema PASSED
tests/contract/test_intrinsic_schemas.py::test_generate_image_schema_is_the_designs PASSED
tests/contract/test_media_api.py::test_media_api_snapshot PASSED        
tests/contract/test_models_tools_api.py::test_models_api_snapshot PASSED
tests/contract/test_models_tools_api.py::test_tools_api_snapshot PASSED 
tests/contract/test_plugins_api.py::test_plugins_api_snapshot PASSED    
tests/contract/test_plugins_api.py::test_commands_json_schema_matches_the_committed_file PASSED
tests/contract/test_prompts_api.py::test_prompts_api_snapshot PASSED    
tests/contract/test_prompts_api.py::test_default_prompt_sections_snapshot PASSED
tests/contract/test_service_api.py::test_service_api_snapshot PASSED    
tests/contract/test_skills_api.py::test_skills_api_snapshot PASSED      
tests/contract/test_task_extension_schema.py::test_task_extension_schema_matches_the_committed_file PASSED
tests/contract/test_task_extension_schema.py::test_core_api_snapshot PASSED
45 passed in 3.05s
exit=0
```

## Agent card without `[media]`: unchanged from 0.8.0

`tests/contract/snapshots/agent-card.json` has no change against the 0.8.0 base
(`git diff 849a91b HEAD -- tests/contract/snapshots/agent-card.json` is empty), and
`test_agent_card.py` asserts the card built without `[media]` equals it.

## Agent card with `[media]`: the snapshot diff

`diff -u tests/contract/snapshots/agent-card.json tests/contract/snapshots/agent-card-media.json`

```diff
@@ -50,6 +50,31 @@
           ]
         },
         "uri": "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/commands/v1"
+      },
+      {
+        "description": "tiny-harness media: accepted and produced media types, limits and services in params; file parts are stored and served by the media route",
+        "params": {
+          "imageGeneration": true,
+          "input": [
+            "image/png",
+            "image/jpeg",
+            "image/webp",
+            "image/gif",
+            "audio/wav",
+            "audio/webm"
+          ],
+          "maxAudioSeconds": 120.0,
+          "maxFileBytes": 20971520.0,
+          "maxMessageBytes": 26214400.0,
+          "mediaPath": "/media",
+          "output": [
+            "image/png",
+            "audio/L16;rate=24000;channels=1"
+          ],
+          "speechToText": true,
+          "textToSpeech": true
+        },
+        "uri": "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/media/v1"
       }
     ],
     "pushNotifications": true,
@@ -60,13 +85,21 @@
     "application/vnd.tiny-harness.task+json",
     "application/vnd.tiny-harness.channel+json",
     "application/vnd.tiny-harness.event+json",
-    "application/a2ui+json"
+    "application/a2ui+json",
+    "image/png",
+    "image/jpeg",
+    "image/webp",
+    "image/gif",
+    "audio/wav",
+    "audio/webm"
   ],
   "defaultOutputModes": [
     "text/plain",
     "application/vnd.tiny-harness.task+json",
     "application/vnd.tiny-harness.channel+json",
-    "application/a2ui+json"
+    "application/a2ui+json",
+    "image/png",
+    "audio/L16;rate=24000;channels=1"
   ],
   "description": "A tiny agent harness: tasks, plans, participants, tools and skills over A2A",
   "name": "tiny-harness",
```

## Schemas and public-API snapshots changed against 0.8.0

`git diff --stat 849a91b HEAD -- tests/contract/snapshots docs/a2a`

```text
 docs/a2a/ext/channel.json | 114 ++++++++++-
 docs/a2a/ext/commands.json | 14 +-
 docs/a2a/ext/commands/v1.md | 22 +++
 docs/a2a/ext/intrinsics/generate_image.json | 48 +++++
 docs/a2a/ext/media.json | 186 ++++++++++++++++++
 docs/a2a/ext/media/v1.md | 151 +++++++++++++++
 docs/a2a/ext/task.json | 6 +-
 docs/a2a/extensions.md | 7 +-
 tests/contract/snapshots/agent-card-media.json | 119 ++++++++++++
 tests/contract/snapshots/settings.schema.json | 213 +++++++++++++++++++++
 tests/contract/snapshots/tiny_harness.config.txt | 10 +-
 .../snapshots/tiny_harness.harness.commands.txt | 8 +-
 .../snapshots/tiny_harness.harness.core.txt | 8 +-
 .../snapshots/tiny_harness.harness.entities.txt | 2 +-
 .../snapshots/tiny_harness.harness.media.txt | 43 +++++
 .../snapshots/tiny_harness.harness.models.txt | 38 +++-
 .../snapshots/tiny_harness.harness.tools.txt | 4 +-
 .../tiny_harness.interaction.renderer.txt | 14 ++
 .../snapshots/tiny_harness.interaction.surface.txt | 4 +
 tests/contract/snapshots/tiny_harness.service.txt | 4 +-
 20 files changed, 991 insertions(+), 24 deletions(-)
```

The public-API snapshots gain exactly the design's names: `tiny_harness.harness.media`
(new: `MediaStore`, `FileMediaStore`, `MediaIntake`, `MediaRef`, `MediaAttachment`,
`MediaCapabilities`, `capabilities`, `guard`, the `Media*` errors, `SpeechWriter`,
`AudioFormat`, `PCM_MEDIA_TYPE`, `ACCEPTED`); `tiny_harness.config` (`MediaConfig`,
`SpeechToTextConfig`, `TextToSpeechConfig`, `ImageGenerationConfig`,
`OpenAIConfig.input_modalities` and `audio_tokens_per_second`, `RetentionConfig.media`);
`tiny_harness.harness.models` (the speech, transcription and image-generation types and
their fakes); `tiny_harness.harness.commands` (`CommandSpec.runs_on`, `ATTACH`);
`tiny_harness.interaction` (media in the renderer and surface API). Every change to an
existing signature adds a keyword argument with a default.
