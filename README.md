# Azure Speech Live Interpreter demo

This Python CLI translates microphone or WAV speech with Azure Speech Live
Interpreter. It prints interim and final translations, can play synthesized
audio, and can save the translated audio as a WAV file.

## Prerequisites

- Python 3.10 or newer.
- An existing Azure Speech resource in a
  [Live Interpreter supported region](https://learn.microsoft.com/azure/ai-services/speech-service/regions#speech-translation).
- Live Interpreter and Personal Voice access on that Speech resource.
- **Cognitive Services Speech User** on the resource when using Microsoft
  Entra authentication.
- A microphone and speaker for interactive use. WAV input doesn't require a
  microphone.

Create a virtual environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Configure a tenant, subscription, and Speech resource

Copy the template and edit the new file:

```bash
cp .env.example .env
```

Set these values in `.env`:

| Variable | Purpose |
| --- | --- |
| `AZURE_CONFIG_DIR` | Azure CLI profile directory for the target tenant. Use an absolute path. |
| `AZURE_TENANT_ID` | Tenant containing the subscription and Speech resource. |
| `AZURE_SUBSCRIPTION_ID` | Subscription containing the Speech resource. |
| `AZURE_SPEECH_RESOURCE_NAME` | Existing Speech resource name. |
| `AZURE_SPEECH_ENDPOINT` | Optional custom endpoint instead of the resource name. |
| `AZURE_SPEECH_AUTH_MODE` | `azure-cli`, `key`, or `auto`. |
| `AZURE_SPEECH_KEY` | Required only for `key` mode. Never commit this value. |
| `AZURE_SPEECH_TARGET_LANGUAGE` | Translation target, such as `fr`, `en`, or `cs`. |
| `AZURE_SPEECH_VOICE` | Optional voice name. Defaults to a matching prebuilt voice for French, English, or Czech. Set to `personal-voice` only when explicitly required. |

Process environment variables take precedence over values from the dotenv file.
CLI options take precedence over both.

For Azure CLI authentication, sign in to the configured profile and select the
target subscription:

```bash
AZURE_CONFIG_DIR="/path/to/azure-cli-profile" az login --tenant "<tenant-id>"
AZURE_CONFIG_DIR="/path/to/azure-cli-profile" az account set --subscription "<subscription-id>"
AZURE_CONFIG_DIR="/path/to/azure-cli-profile" az account show
```

The application routes `AzureCliCredential` through `AZURE_SUBSCRIPTION_ID`
when provided, which also selects that subscription's tenant. It falls back to
`AZURE_TENANT_ID` when no subscription is configured.

## Run the demo

The default configuration file is `.env`:

```bash
python3 sample_code.py
```

Use a different customer or tenant configuration:

```bash
python3 sample_code.py --env-file /path/to/customer.env
```

Prebuilt neural voices are selected by default:

| Target language | Default voice |
| --- | --- |
| `fr` | `fr-FR-DeniseNeural` |
| `en` | `en-US-JennyNeural` |
| `cs` or `cz` | `cs-CZ-VlastaNeural` |

Choose another prebuilt voice with `--voice`, or explicitly enable the restricted
Personal Voice mode:

```bash
python3 sample_code.py --target-language de --voice de-DE-KatjaNeural
python3 sample_code.py --voice personal-voice
```

`personal-voice` requires Personal Voice access on the exact Speech resource.
Targets without a listed default require `--voice` or `AZURE_SPEECH_VOICE`.

Use a PCM WAV file and save the translated audio:

```bash
python3 sample_code.py \
  --env-file /path/to/customer.env \
  --wav /path/to/input.wav \
  --output-wav translated.wav \
  --no-play-audio
```

Use `--no-env-file` to rely only on the current process environment and CLI
arguments. Run `python3 sample_code.py --help` for all options.

## Authentication modes

- `azure-cli`: uses the Azure CLI profile, tenant, and subscription from the
  configuration.
- `key`: uses `AZURE_SPEECH_KEY` for a resource where local authentication is
  enabled.
- `auto`: uses a non-empty key when present; otherwise it uses Azure CLI.

Keys and bearer tokens are never accepted as CLI arguments or printed.

## Troubleshooting

- Verify the selected CLI account with `az account show` using the same
  `AZURE_CONFIG_DIR`.
- For 401, 403, authorization, or RBAC errors, verify the tenant, subscription,
  signed-in identity, and **Cognitive Services Speech User** assignment on the
  exact Speech resource.
- For `User is not authorized to use Live Interpreter` or Personal Voice
  errors, verify feature approval on the exact Speech resource.
- For audio-device errors, provide a valid PCM WAV file with `--wav`.
