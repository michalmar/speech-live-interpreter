import argparse
import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

import sample_code


class FakeEvent:
    def __init__(self, result=None, cancellation_details=None):
        self.result = result
        self.cancellation_details = cancellation_details


class FakeResult:
    def __init__(self, text="", translations=None, reason=None, audio=b""):
        self.text = text
        self.translations = translations or {}
        self.reason = reason
        self.audio = audio


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class FakeRecognizer:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.recognizing = FakeSignal()
        self.recognized = FakeSignal()
        self.synthesizing = FakeSignal()
        self.canceled = FakeSignal()
        self.session_started = FakeSignal()
        self.session_stopped = FakeSignal()
        self.started = False
        self.stopped = False

    def start_continuous_recognition(self):
        self.started = True
        for callback in self.session_started.callbacks:
            callback(FakeEvent())
        for callback in self.synthesizing.callbacks:
            callback(FakeEvent(FakeResult(audio=b"\x00\x00" * 8)))
        for callback in self.session_stopped.callbacks:
            callback(FakeEvent())

    def stop_continuous_recognition(self):
        self.stopped = True


class FakeConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.target_languages = []
        self.voice_name = ""

    def add_target_language(self, language):
        self.target_languages.append(language)

    def set_speech_synthesis_output_format(self, output_format):
        self.output_format = output_format


class FakeAutoDetect:
    calls = 0

    def __init__(self):
        type(self).calls += 1


def fake_sdk():
    return types.SimpleNamespace(
        translation=types.SimpleNamespace(
            SpeechTranslationConfig=FakeConfig,
            TranslationRecognizer=FakeRecognizer,
        ),
        languageconfig=types.SimpleNamespace(
            AutoDetectSourceLanguageConfig=FakeAutoDetect,
        ),
        audio=types.SimpleNamespace(
            AudioConfig=lambda **kwargs: types.SimpleNamespace(kwargs=kwargs)
        ),
        ResultReason=types.SimpleNamespace(
            TranslatedSpeech="translated",
            NoMatch="nomatch",
        ),
        SpeechSynthesisOutputFormat=types.SimpleNamespace(
            Riff16Khz16BitMonoPcm="riff"
        ),
    )


class SampleCodeTests(unittest.TestCase):
    def test_endpoint_construction_and_normalization(self):
        self.assertEqual(
            sample_code.build_universal_v2_endpoint("demo-resource"),
            "wss://demo-resource.cognitiveservices.azure.com/stt/speech/universal/v2",
        )
        self.assertEqual(
            sample_code.build_universal_v2_endpoint(
                endpoint="https://example.cognitiveservices.azure.com"
            ),
            "wss://example.cognitiveservices.azure.com/stt/speech/universal/v2",
        )

    def test_endpoint_validation(self):
        with self.assertRaises(sample_code.ConfigurationError):
            sample_code.build_universal_v2_endpoint()
        with self.assertRaises(sample_code.ConfigurationError):
            sample_code.build_universal_v2_endpoint(endpoint="https://example.invalid/wrong")
        with self.assertRaises(sample_code.ConfigurationError):
            sample_code.build_universal_v2_endpoint(
                endpoint="https://user:secret@example.com"
            )
        with self.assertRaises(sample_code.ConfigurationError):
            sample_code.build_universal_v2_endpoint(
                endpoint="https://example.com?token=secret"
            )

    def test_timeout_must_be_finite_and_positive(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                with self.assertRaises(sample_code.ConfigurationError):
                    sample_code._positive_timeout(value)
        with self.assertRaises(SystemExit):
            sample_code.parse_args(
                ["--no-env-file", "--resource-name", "demo", "--timeout", "nan"]
            )
        args = sample_code.parse_args(["--no-env-file", "--resource-name", "demo"])
        args.timeout = float("nan")
        with self.assertRaises(sample_code.ConfigurationError):
            sample_code.load_config(
                args, {"AZURE_SPEECH_KEY": "secret", "AZURE_CONFIG_DIR": "/profile"}
            )

    def test_config_requires_key_and_validates_wav(self):
        args = argparse.Namespace(
            target_language="fr",
            resource_name="demo",
            endpoint=None,
            input_wav=None,
            output_wav=None,
            timeout=10,
            no_play_audio=True,
            auth_mode="key",
        )
        with self.assertRaisesRegex(sample_code.ConfigurationError, "requires"):
            sample_code.load_config(args, {})
        with tempfile.TemporaryDirectory() as directory:
            args.input_wav = Path(directory) / "missing.wav"
            with self.assertRaises(sample_code.ConfigurationError):
                sample_code.load_config(
                    args, {"AZURE_SPEECH_KEY": "secret", "AZURE_CONFIG_DIR": "/profile"}
                )

    def test_auto_auth_mode_prefers_key_when_present(self):
        args = sample_code.parse_args(["--no-env-file", "--resource-name", "demo"])
        config = sample_code.load_config(
            args,
            {"AZURE_SPEECH_KEY": "secret", "AZURE_CONFIG_DIR": "/profile"},
        )
        self.assertEqual(config.auth_mode, "key")
        self.assertEqual(config.key, "secret")

    def test_auto_auth_mode_falls_back_to_azure_cli(self):
        args = sample_code.parse_args(["--no-env-file", "--resource-name", "demo"])
        config = sample_code.load_config(args, {"AZURE_CONFIG_DIR": "/profile"})
        self.assertEqual(config.auth_mode, "azure-cli")
        self.assertIsNone(config.key)

    def test_key_auth_mode_requires_a_key(self):
        args = sample_code.parse_args(
            ["--no-env-file", "--resource-name", "demo", "--auth-mode", "key"]
        )
        with self.assertRaisesRegex(sample_code.ConfigurationError, "AZURE_SPEECH_KEY"):
            sample_code.load_config(args, {"AZURE_CONFIG_DIR": "/profile"})

    def test_azure_cli_auth_mode_requires_config_dir(self):
        args = sample_code.parse_args(
            ["--no-env-file", "--resource-name", "demo", "--auth-mode", "azure-cli"]
        )
        with self.assertRaisesRegex(sample_code.ConfigurationError, "AZURE_CONFIG_DIR"):
            sample_code.load_config(args, {})

    def test_cli_reads_non_secret_environment_defaults(self):
        with mock.patch.dict(
            os.environ,
            {
                "AZURE_SPEECH_RESOURCE_NAME": "demo",
                "AZURE_SPEECH_TARGET_LANGUAGE": "de",
                "AZURE_SPEECH_TIMEOUT": "15",
                "AZURE_SPEECH_AUTH_MODE": "azure-cli",
            },
            clear=True,
        ):
            args = sample_code.parse_args(["--no-env-file"])
        self.assertEqual(args.resource_name, "demo")
        self.assertEqual(args.target_language, "de")
        self.assertEqual(args.timeout, 15.0)
        self.assertEqual(args.auth_mode, "azure-cli")

    def test_dotenv_loads_tenant_subscription_and_resource(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "customer.env"
            env_file.write_text(
                "\n".join(
                    (
                        "AZURE_CONFIG_DIR=/profiles/customer",
                        "AZURE_TENANT_ID=customer-tenant",
                        "AZURE_SUBSCRIPTION_ID=customer-subscription",
                        "AZURE_SPEECH_AUTH_MODE=azure-cli",
                        "AZURE_SPEECH_RESOURCE_NAME=customer-speech",
                        "AZURE_SPEECH_TARGET_LANGUAGE=de",
                    )
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                args = sample_code.parse_args(["--env-file", str(env_file)])
                config = sample_code.load_config(args)
        self.assertEqual(config.tenant_id, "customer-tenant")
        self.assertEqual(config.subscription_id, "customer-subscription")
        self.assertEqual(config.auth_mode, "azure-cli")
        self.assertEqual(config.target_language, "de")
        self.assertEqual(
            config.endpoint,
            "wss://customer-speech.cognitiveservices.azure.com"
            "/stt/speech/universal/v2",
        )

    def test_process_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "customer.env"
            env_file.write_text(
                "AZURE_SPEECH_RESOURCE_NAME=file-resource\n"
                "AZURE_CONFIG_DIR=/profiles/customer\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"AZURE_SPEECH_RESOURCE_NAME": "process-resource"},
                clear=True,
            ):
                args = sample_code.parse_args(["--env-file", str(env_file)])
                config = sample_code.load_config(args)
        self.assertIn("process-resource", config.endpoint)

    def test_explicit_missing_dotenv_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.env"
            with self.assertRaisesRegex(
                sample_code.ConfigurationError, "does not exist"
            ):
                sample_code.parse_args(["--env-file", str(missing)])

    def test_sdk_key_configuration_uses_target_voice_and_open_range(self):
        FakeAutoDetect.calls = 0
        config = sample_code.AppConfig(
            key="not-printed",
            endpoint="wss://demo.cognitiveservices.azure.com/stt/speech/universal/v2",
            target_language="de",
            input_wav=None,
            output_wav=None,
            timeout_seconds=1,
            play_audio=False,
        )
        sdk = fake_sdk()
        translation, auto_detect = sample_code.create_translation_components(config, sdk)
        self.assertEqual(translation.kwargs["subscription"], "not-printed")
        self.assertEqual(translation.kwargs["endpoint"], config.endpoint)
        self.assertEqual(translation.target_languages, ["de"])
        self.assertEqual(translation.voice_name, sample_code.PERSONAL_VOICE)
        self.assertEqual(translation.output_format, "riff")
        self.assertIsInstance(auto_detect, FakeAutoDetect)
        self.assertEqual(FakeAutoDetect.calls, 1)

    def test_sdk_azure_cli_configuration_uses_token_credential(self):
        credential = object()
        config = sample_code.AppConfig(
            key=None,
            endpoint="wss://demo.cognitiveservices.azure.com/stt/speech/universal/v2",
            target_language="de",
            input_wav=None,
            output_wav=None,
            timeout_seconds=1,
            play_audio=False,
            auth_mode="azure-cli",
            tenant_id="customer-tenant",
            subscription_id="customer-subscription",
        )
        with mock.patch.dict(os.environ, {"AZURE_CONFIG_DIR": "/profile"}, clear=True):
            with mock.patch(
                "sample_code.create_azure_cli_credential", return_value=credential
            ) as create_credential:
                translation, _ = sample_code.create_translation_components(config, fake_sdk())
        self.assertIs(translation.kwargs["token_credential"], credential)
        self.assertNotIn("subscription", translation.kwargs)
        create_credential.assert_called_once_with(
            "customer-tenant",
            "customer-subscription",
        )

    def test_azure_cli_credential_is_constructed_lazily(self):
        credential = object()
        constructor = mock.Mock(return_value=credential)
        identity_module = types.ModuleType("azure.identity")
        identity_module.AzureCliCredential = constructor
        with mock.patch.dict(
            sys.modules, {"azure.identity": identity_module}
        ), mock.patch.dict(os.environ, {"AZURE_CONFIG_DIR": "/profile"}, clear=True):
            result = sample_code.create_azure_cli_credential(
                "customer-tenant",
                "customer-subscription",
            )
        self.assertIs(result, credential)
        constructor.assert_called_once_with(
            tenant_id="customer-tenant",
            subscription="customer-subscription",
        )

    def test_azure_cli_credential_constructor_errors_are_not_swallowed(self):
        constructor = mock.Mock(side_effect=RuntimeError("credential setup failed"))
        identity_module = types.ModuleType("azure.identity")
        identity_module.AzureCliCredential = constructor
        with mock.patch.dict(
            sys.modules, {"azure.identity": identity_module}
        ), mock.patch.dict(os.environ, {"AZURE_CONFIG_DIR": "/profile"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "credential setup failed"):
                sample_code.create_azure_cli_credential()

    def test_event_formatting_and_cancellation(self):
        sdk = fake_sdk()
        recognizing = sample_code.format_recognizing_event(
            FakeEvent(FakeResult("hello", {"fr": "bonjour"}))
        )
        self.assertEqual(recognizing, "RECOGNIZING: hello -> fr: bonjour")
        recognized = sample_code.format_recognized_event(
            FakeEvent(FakeResult("hello", {"fr": "bonjour"}, "translated")), sdk
        )
        self.assertEqual(recognized, "RECOGNIZED: hello -> fr: bonjour")
        canceled = sample_code.format_canceled_event(
            FakeEvent(
                cancellation_details=types.SimpleNamespace(
                    reason="Error", error_details="Personal Voice is not approved"
                )
            )
        )
        self.assertIn("Personal Voice approval", canceled)
        generic_auth = sample_code.format_canceled_event(
            FakeEvent(
                cancellation_details=types.SimpleNamespace(
                    reason="Error", error_details="not authorized to call Speech API"
                )
            )
        )
        self.assertIn("Cognitive Services Speech User", generic_auth)
        self.assertNotIn("Personal Voice", generic_auth)
        generic_error = sample_code.format_canceled_event(
            FakeEvent(
                cancellation_details=types.SimpleNamespace(
                    reason="Error", error_details="service unavailable"
                )
            )
        )
        self.assertNotIn("Personal Voice", generic_error)

    def test_cancellation_is_reported_once_by_main(self):
        event = FakeEvent(
            cancellation_details=types.SimpleNamespace(
                reason="Error",
                error_details="User is not authorized to use Live Interpreter.",
            )
        )

        class CancelingRecognizer(FakeRecognizer):
            def start_continuous_recognition(self):
                for callback in self.canceled.callbacks:
                    callback(event)

        sdk = fake_sdk()
        sdk.translation.TranslationRecognizer = CancelingRecognizer
        config = sample_code.AppConfig(
            key="secret",
            endpoint="wss://demo.cognitiveservices.azure.com/stt/speech/universal/v2",
            target_language="fr",
            input_wav=None,
            output_wav=None,
            timeout_seconds=1,
            play_audio=False,
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(sample_code.SessionError):
                sample_code.run_session(config, sdk, sleep=lambda _: None)
        output = stderr.getvalue()
        self.assertEqual(output, "")
        config = object()
        with mock.patch("sample_code.parse_args", return_value=object()), mock.patch(
            "sample_code.load_config", return_value=config
        ), mock.patch(
            "sample_code.run_session",
            side_effect=sample_code.SessionError(sample_code.format_canceled_event(event)),
        ):
            with contextlib.redirect_stderr(stderr := io.StringIO()):
                self.assertEqual(sample_code.main([]), 2)
        self.assertEqual(stderr.getvalue().count("User is not authorized to use Live Interpreter."), 1)

    def test_run_session_subscribes_and_stops(self):
        config = sample_code.AppConfig(
            key="secret",
            endpoint="wss://demo.cognitiveservices.azure.com/stt/speech/universal/v2",
            target_language="fr",
            input_wav=None,
            output_wav=None,
            timeout_seconds=1,
            play_audio=False,
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            sample_code.run_session(config, fake_sdk(), sleep=lambda _: None)
        output = stdout.getvalue()
        self.assertIn("SESSION: started", output)
        self.assertIn("SYNTHESIZING", output)
        self.assertIn("SESSION: stopped", output)

    def test_run_session_wraps_sdk_setup_errors(self):
        class BrokenAudio:
            def AudioConfig(self, **kwargs):
                raise RuntimeError("audio device unavailable")

        sdk = fake_sdk()
        sdk.audio = BrokenAudio()
        config = sample_code.AppConfig(
            key="secret",
            endpoint="wss://demo.cognitiveservices.azure.com/stt/speech/universal/v2",
            target_language="fr",
            input_wav=None,
            output_wav=None,
            timeout_seconds=1,
            play_audio=False,
        )
        with self.assertRaisesRegex(sample_code.SessionError, "audio device unavailable"):
            sample_code.run_session(config, sdk, sleep=lambda _: None)

    def test_audio_collector_writes_pcm_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "translated.wav"
            collector = sample_code.AudioCollector(output_path, play_audio=False)
            collector.add(b"\x00\x00" * 8)
            collector.finish()
            with wave.open(str(output_path), "rb") as wav_file:
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), 16000)
                self.assertEqual(wav_file.getnframes(), 8)


if __name__ == "__main__":
    unittest.main()
