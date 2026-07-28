# utils.py
import re
import json
import subprocess
import os
from typing import Optional, Any, Type, TypedDict, List, Dict
from pydantic import BaseModel, Field
from pathlib import Path
import requests
import time
import random
import shutil
import threading
from foamagent import paths
from foamagent.config import Config
from foamagent.execution import get_execution_backend
from foamagent.logger import get_logger

logger = get_logger(__name__)

# Import errors for optional extras are reported with the command that fixes them,
# because the bare ModuleNotFoundError names a transitive package the user never chose.
_EXTRA_HINTS = {
    "rag-local": "pip install 'foamagent[rag-local]'",
    "direct-api": "pip install 'foamagent[direct-api]'",
    "bedrock": "pip install 'foamagent[bedrock]'",
    "ollama": "pip install 'foamagent[ollama]'",
}


def _require(extra: str, importer):
    """Import an optional dependency, or explain which extra provides it."""
    try:
        return importer()
    except ImportError as exc:
        raise ImportError(
            f"This feature needs the '{extra}' extra, which is not installed "
            f"({exc}). Install it with: {_EXTRA_HINTS.get(extra, extra)}"
        ) from exc


def _botocore_client_error():
    """Return botocore's ClientError, or None when boto3 is not installed.

    Throttling detection must work without the AWS extras, so callers treat a missing
    botocore as "this cannot be a ClientError" rather than as an error.
    """
    try:
        from botocore.exceptions import ClientError
    except ImportError:
        return None
    return ClientError


def _lfs_pointer_reason(path: Path) -> Optional[str]:
    """Return an explanation if `path` is an unfetched Git LFS pointer, else None.

    A pointer file is ~130 bytes of text starting with a version URL. Loading one as a
    FAISS index fails with `Index type 0x73726576 ("vers") not recognized`, which names
    the first four bytes of the word "version" and tells the reader nothing.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
    except OSError:
        return None

    if not head.startswith(b"version https://git-lfs.github.com/spec/"):
        return None

    return (
        f"{path} is an unfetched Git LFS pointer, not the real index. "
        "Fetch the database contents with: git lfs install --local && git lfs pull"
    )


def get_embedding_model(config: Optional[Config] = None):
    """Return an embedding model based on the provided config.

    Note: historically this module accessed Config.* class attributes at import time.
    That works for defaults but breaks when callers pass a customized Config instance.
    """
    cfg = config or Config()

    provider = (cfg.embedding_provider or "openai").lower()
    model = cfg.embedding_model

    if provider == "openai":
        def _import():
            from langchain_openai.embeddings import OpenAIEmbeddings
            return OpenAIEmbeddings
        return _require("direct-api", _import)(model=model)
    if provider == "huggingface":
        def _import():
            from langchain_huggingface import HuggingFaceEmbeddings
            return HuggingFaceEmbeddings
        return _require("rag-local", _import)(model_name=model)
    if provider == "ollama":
        def _import():
            from langchain_ollama import OllamaEmbeddings
            return OllamaEmbeddings
        return _require("ollama", _import)(model=model)

    raise ValueError(f"Unsupported embedding provider: {provider}")


def _preferred_faiss_base_dir() -> Path:
    """Return the FAISS directory to load from: a built index if there is one.

    Detection failing is not an error here; it only means the shipped index is used.
    """
    try:
        from foamagent.environment import detect_environment
        from foamagent.indexing import resolve_faiss_base_dir

        environment = detect_environment()
        return resolve_faiss_base_dir(environment if environment.detected else None)
    except Exception as exc:
        logger.debug("Falling back to the shipped FAISS index: %s", exc)
        return paths.database_dir() / "faiss"


def load_faiss_dbs(config: Optional[Config] = None):
    def _import():
        from langchain_community.vectorstores import FAISS
        return FAISS

    FAISS = _require("rag-local", _import)

    cfg = config or Config()
    embedding_model = get_embedding_model(cfg)

    # An index built from the installed OpenFOAM describes that OpenFOAM; the one shipped
    # in database/ describes Foundation v10. Prefer the former when it exists.
    base_dir = _preferred_faiss_base_dir()

    # Sanitize model name for directory usage
    model_dir_name = (cfg.embedding_model or "").replace("/", "_").replace(":", "_")
    db_path = base_dir / model_dir_name

    logger.info("Loading FAISS indices from: %s with model: %s", db_path, cfg.embedding_model)

    dbs = {}
    indices = [
        "openfoam_allrun_scripts",
        "openfoam_tutorials_structure",
        "openfoam_tutorials_details",
        "openfoam_command_help",
    ]

    for index in indices:
        index_path = db_path / index
        if not index_path.exists():
            logger.warning("Index path does not exist: %s", index_path)
            continue

        pointer_reason = _lfs_pointer_reason(index_path / "index.faiss")
        if pointer_reason:
            logger.error("Failed to load index %s: %s", index, pointer_reason)
            continue

        try:
            dbs[index] = FAISS.load_local(
                str(index_path), embedding_model, allow_dangerous_deserialization=True
            )
        except Exception as e:
            logger.error("Failed to load index %s: %s", index, e)

    return dbs


# FAISS indices are loaded on first use, not at import: constructing the embedding model
# downloads ~1GB of weights, which must not happen just because someone imported the
# package (a test collection, `--help`, or an MCP handshake).
_FAISS_DB_CACHE: Optional[dict] = None


def get_faiss_dbs(config: Optional[Config] = None) -> dict:
    """Return the loaded FAISS indices, loading them on first call."""
    global _FAISS_DB_CACHE
    if _FAISS_DB_CACHE is None:
        _FAISS_DB_CACHE = load_faiss_dbs(config)
    return _FAISS_DB_CACHE


def set_faiss_dbs(dbs: dict) -> None:
    """Replace the cached indices (used when embedding settings change at runtime)."""
    global _FAISS_DB_CACHE
    _FAISS_DB_CACHE = dbs

class FoamfilePydantic(BaseModel):
    file_name: str = Field(description="Name of the OpenFOAM input file")
    folder_name: str = Field(description="Folder where the foamfile should be stored")
    content: str = Field(description="Content of the OpenFOAM file, written in OpenFOAM dictionary format")

class FoamPydantic(BaseModel):
    list_foamfile: List[FoamfilePydantic] = Field(description="List of OpenFOAM configuration files")

class ResponseWithThinkPydantic(BaseModel):
    think: str = Field(description="Thought process of the LLM")
    response: str = Field(description="Response of the LLM")

class LLMService:
    def __init__(self, config: object):
        self.model_version = getattr(config, "model_version", "gpt-4o")
        self.temperature = getattr(config, "temperature", 0)
        self.model_provider = getattr(config, "model_provider", "openai")
        self._config = config
        
        # Initialize statistics
        self.total_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.failed_calls = 0
        self.retry_count = 0
        # One service is shared by the whole run, and parallel_no_context generates files
        # concurrently, so the counters need a lock to stay accurate.
        self._stats_lock = threading.Lock()

        # The client is built on first use. Constructing it reads credentials (and, for
        # some providers, starts a local server), so an unused service must stay inert.
        self._llm = None

    def _count(self, **deltas: int) -> None:
        with self._stats_lock:
            for name, delta in deltas.items():
                setattr(self, name, getattr(self, name) + delta)

    @property
    def llm(self):
        if self._llm is None:
            self._llm = self._build_llm(self._config)
        return self._llm

    @llm.setter
    def llm(self, value):
        self._llm = value

    def _build_llm(self, config: object):
        if self.model_provider.lower() == "bedrock":
            def _import():
                from langchain_aws import ChatBedrockConverse
                return ChatBedrockConverse

            ChatBedrockConverse = _require("bedrock", _import)
            from foamagent import tracking_aws

            bedrock_runtime = tracking_aws.new_default_client()
            return ChatBedrockConverse(
                client=bedrock_runtime,
                model_id=self.model_version,
                temperature=self.temperature,
                max_tokens=8192
            )
        elif self.model_provider.lower() == "anthropic":
            def _import():
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic

            return _require("direct-api", _import)(
                model=self.model_version,
                temperature=self.temperature
            )
        elif self.model_provider.lower() == "openai":
            # Usage-based API access (requires OPENAI_API_KEY or equivalent OpenAI SDK config).
            # An OpenAI-compatible endpoint (OpenRouter, vLLM, LiteLLM, ...) can be used by
            # setting FOAMAGENT_OPENAI_BASE_URL.
            init_kwargs = {
                "model_provider": self.model_provider,
                "temperature": self.temperature,
            }
            base_url = getattr(config, "openai_base_url", "") or ""
            if base_url:
                init_kwargs["base_url"] = base_url

            def _import():
                from langchain.chat_models import init_chat_model
                return init_chat_model

            return _require("direct-api", _import)(self.model_version, **init_kwargs)
        elif self.model_provider.lower() in {"openai-codex", "codex", "chatgpt-oauth"}:
            raise ValueError(
                "The openai-codex provider read a Codex CLI login token off disk and "
                "replayed it against ChatGPT's backend. Foam-Agent no longer does that: a "
                "credential another tool obtained for its own use is not this one's to "
                "spend.\n"
                "\n"
                "To use Codex CLI, run it as the harness -- `foamagent install codex-cli` "
                "-- and it will drive Foam-Agent's tools with its own session. For an API "
                "key, set FOAMAGENT_MODEL_PROVIDER=openai with OPENAI_API_KEY."
            )
        elif self.model_provider.lower() == "ollama":
            def _import():
                from langchain_ollama import ChatOllama
                return ChatOllama

            ChatOllama = _require("ollama", _import)

            try:
                requests.get("http://localhost:11434/api/version", timeout=2)
                # If request successful, service is running
            except requests.exceptions.RequestException:
                logger.info("Ollama is not running, starting it...")
                subprocess.Popen(["ollama", "serve"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
                # Wait for service to start
                time.sleep(5)  # Give it 3 seconds to initialize

            return ChatOllama(
                model=self.model_version,
                temperature=self.temperature,
                num_predict=-1,
                num_ctx=131072,
                base_url="http://localhost:11434"
            )
        elif self.model_provider.lower() == "deepseek":
            def _import():
                from langchain_openai import ChatOpenAI
                return ChatOpenAI

            ChatOpenAI = _require("direct-api", _import)

            reasoning = os.getenv("FOAMAGENT_REASONING_EFFORT", "max")
            if reasoning not in ("low", "medium", "high", "max"):
                reasoning = "max"
            # Note: temperature is ignored by DeepSeek in thinking mode.
            return ChatOpenAI(
                model=self.model_version,
                temperature=self.temperature,
                base_url="https://api.deepseek.com/v1",
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                reasoning_effort=reasoning,
                extra_body={"thinking": {"type": "enabled"}},
            )
        else:
            raise ValueError(f"{self.model_provider} is not a supported model_provider")
    
    def _is_structured_output_error(self, error: Exception) -> bool:
        """Check whether an exception means the model returned an off-schema answer.

        Covers Pydantic validation errors (wrong shape, missing field) and the JSON
        decoding errors raised when the answer is not valid JSON at all. These are
        worth retrying because a second attempt often returns the correct shape.
        """
        from pydantic import ValidationError

        if isinstance(error, (ValidationError, json.JSONDecodeError)):
            return True

        name = type(error).__name__
        return name in {"OutputParserException", "ValidationError", "JSONDecodeError"}

    def _is_throttling_error(self, error: Exception) -> bool:
        """
        Check if an exception is a throttling-related error.

        Args:
            error: The exception to check
            
        Returns:
            True if it's a throttling error, False otherwise
        """
        # Check ClientError with specific error codes
        client_error = _botocore_client_error()
        if client_error is not None and isinstance(error, client_error):
            error_code = error.response.get('Error', {}).get('Code', '')
            return error_code in ('Throttling', 'TooManyRequestsException', 'ThrottlingException')
        
        # Check for ThrottlingException and throttling-related error messages
        error_type = type(error).__name__
        error_str = str(error)
        
        throttling_indicators = (
            error_type == 'ThrottlingException',
            'ThrottlingException' in error_str,
            'Too many tokens' in error_str,
            'reached max retries' in error_str
        )
        
        return any(throttling_indicators)
    
    def _handle_throttling_retry(self, error: Exception, retry_count: int, max_retries: int) -> Optional[int]:
        """
        Handle throttling error by implementing exponential backoff retry logic.
        
        Args:
            error: The throttling exception
            retry_count: Current retry attempt number
            max_retries: Maximum number of retries allowed
            
        Returns:
            The updated retry count if retry should continue, None if max retries exceeded
        """
        retry_count += 1
        self._count(retry_count=1)
        
        if retry_count > max_retries:

            logger.info(f"Maximum retries ({max_retries}) exceeded: {str(error)}")
            return None
        
        # Exponential backoff with jitter
        base_delay = 1.0
        max_delay = 60.0
        delay = min(max_delay, base_delay * (2 ** (retry_count - 1)))
        jitter = random.uniform(0, 0.1 * delay)
        sleep_time = delay + jitter
        
        logger.info(f"ThrottlingException occurred: {str(error)}. Retrying in {sleep_time:.2f} seconds (attempt {retry_count}/{max_retries})")
        time.sleep(sleep_time)
        
        return retry_count

    def invoke(self,
              user_prompt: str, 
              system_prompt: Optional[str] = None, 
              pydantic_obj: Optional[Type[BaseModel]] = None,
              max_retries: int = 10) -> Any:
        """
        Invoke the LLM with the given prompts and return the response.
        
        Args:
            user_prompt: The user's prompt
            system_prompt: Optional system prompt
            pydantic_obj: Optional Pydantic model for structured output
            max_retries: Maximum number of retries for throttling errors
            
        Returns:
            The LLM response with token usage statistics
        """
        self._count(total_calls=1)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        # Calculate prompt tokens
        prompt_tokens = 0
        for message in messages:
            prompt_tokens += self.llm.get_num_tokens(message["content"])
        
        retry_count = 0
        structured_retry_count = 0
        max_structured_retries = 3
        while True:
            try:
                if pydantic_obj:
                    if self.model_provider.lower() == "deepseek":
                        # DeepSeek thinking mode does not support response_format,
                        # so with_structured_output fails. Use JSON prompt fallback.
                        schema = pydantic_obj.model_json_schema()
                        json_instruction = (
                            "Return ONLY valid JSON (no markdown, no extra text) matching this schema:\n"
                            + str(schema)
                        )
                        json_messages = list(messages)
                        json_messages.append({"role": "user", "content": json_instruction})
                        raw_response = self.llm.invoke(json_messages)
                        raw_text = raw_response.content
                        # Strip markdown fences if present
                        t = raw_text.strip()
                        if t.startswith("```"):
                            t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t)
                            t = re.sub(r"\n?```\s*$", "", t).strip()
                        response = pydantic_obj.model_validate_json(t)
                    else:
                        structured_llm = self.llm.with_structured_output(pydantic_obj)
                        response = structured_llm.invoke(messages)
                else:
                    response = self.llm.invoke(messages)
                    response = response.content

                # Calculate completion tokens
                response_content = str(response)
                completion_tokens = self.llm.get_num_tokens(response_content)
                total_tokens = prompt_tokens + completion_tokens
                
                # Update statistics
                self._count(
                    total_prompt_tokens=prompt_tokens,
                    total_completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
                
                return response
                
            except Exception as e:
                if self._is_throttling_error(e):
                    logger.info(f"ThrottlingException occurred: {str(e)}.")
                    logger.info(f"Retrying: {retry_count + 1}/{max_retries}")
                    retry_count = self._handle_throttling_retry(e, retry_count, max_retries)
                    if retry_count is None:
                        # Max retries exceeded
                        self._count(failed_calls=1)
                        raise Exception(f"Maximum retries ({max_retries}) exceeded for throttling error: {str(e)}")
                    continue  # Retry the request
                elif pydantic_obj is not None and self._is_structured_output_error(e) \
                        and structured_retry_count < max_structured_retries:
                    # The model answered with a shape that does not match the schema
                    # (e.g. a bare JSON array where an object is expected). Ask again
                    # with the mismatch quoted back, rather than failing the workflow.
                    structured_retry_count += 1
                    self._count(retry_count=1)
                    logger.info(
                        f"Structured output did not match {pydantic_obj.__name__}: {str(e)[:200]}. "
                        f"Retrying: {structured_retry_count}/{max_structured_retries}"
                    )
                    messages = list(messages) + [{
                        "role": "user",
                        "content": (
                            "Your previous answer did not match the required schema and was rejected "
                            f"with this error:\n{str(e)[:500]}\n"
                            "Return ONLY a JSON object matching this schema (no markdown, no extra text):\n"
                            + str(pydantic_obj.model_json_schema())
                        ),
                    }]
                    continue
                else:
                    logger.info(f"Non-throttling error occurred: {str(e)}.")

                    # Non-throttling error: log and raise
                    logger.error(f"Error occurred in LLM service: {str(e)}")
                    client_error = _botocore_client_error()
                    if client_error is not None and isinstance(e, client_error):
                        logger.info(e.response)
                    self._count(failed_calls=1)
                    raise e
    
    def get_statistics(self) -> dict:
        """
        Get the current statistics of the LLM service.
        
        Returns:
            Dictionary containing various statistics
        """
        return {
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "retry_count": self.retry_count,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "average_prompt_tokens": self.total_prompt_tokens / self.total_calls if self.total_calls > 0 else 0,
            "average_completion_tokens": self.total_completion_tokens / self.total_calls if self.total_calls > 0 else 0,
            "average_tokens": self.total_tokens / self.total_calls if self.total_calls > 0 else 0
        }
    
    def print_statistics(self) -> None:
        """
        Print the current statistics of the LLM service.
        """
        stats = self.get_statistics()
        logger.info("\n<LLM Service Statistics>")
        logger.info(f"Total calls: {stats['total_calls']}")
        logger.error(f"Failed calls: {stats['failed_calls']}")
        logger.info(f"Total retries: {stats['retry_count']}")
        logger.info(f"Total prompt tokens: {stats['total_prompt_tokens']}")
        logger.info(f"Total completion tokens: {stats['total_completion_tokens']}")
        logger.info(f"Total tokens: {stats['total_tokens']}")
        logger.info(f"Average prompt tokens per call: {stats['average_prompt_tokens']:.2f}")
        logger.info(f"Average completion tokens per call: {stats['average_completion_tokens']:.2f}")
        logger.info(f"Average tokens per call: {stats['average_tokens']:.2f}\n")
        logger.info("</LLM Service Statistics>")

class GraphState(TypedDict):
    user_requirement: str
    config: Config
    case_dir: str
    tutorial: str
    case_name: str
    subtasks: List[dict]
    current_subtask_index: int
    error_command: Optional[str]
    error_content: Optional[str]
    loop_count: int
    # Additional state fields that will be added during execution
    llm_service: Optional['LLMService']
    case_stats: Optional[dict]
    tutorial_reference: Optional[str]
    case_path_reference: Optional[str]
    dir_structure_reference: Optional[str]
    case_info: Optional[str]
    allrun_reference: Optional[str]
    dir_structure: Optional[dict]
    commands: Optional[List[str]]
    foamfiles: Optional[dict]
    error_logs: Optional[List[str]]
    history_text: Optional[List[str]]
    case_domain: Optional[str]
    case_category: Optional[str]
    case_solver: Optional[str]
    # Mesh-related state fields
    mesh_info: Optional[dict]
    mesh_commands: Optional[List[str]]
    custom_mesh_used: Optional[bool]
    mesh_type: Optional[str]
    custom_mesh_path: Optional[str]
    # Review and rewrite related fields
    review_analysis: Optional[str]
    rewrite_plan: Optional[dict]
    input_writer_mode: Optional[str]
    similar_case_advice: Optional[dict]
    # Routing decision cache
    requires_hpc: Optional[bool]
    requires_visualization: Optional[bool]
    # HPC-related fields
    job_id: Optional[str]
    cluster_info: Optional[dict]
    slurm_script_path: Optional[str]
    termination_reason: Optional[str]

def tokenize(text: str) -> str:
    # Replace underscores with spaces
    text = text.replace('_', ' ')
    # Insert a space between a lowercase letter and an uppercase letter (global match)
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)
    return text.lower()

def save_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    logger.info(f"Saved file at {path}")

def read_file(path: str) -> str:
    if os.path.exists(path):
        with open(path, 'r') as f:
            return f.read()
    return ""

def list_case_files(case_dir: str) -> str:
    files = [f for f in os.listdir(case_dir) if os.path.isfile(os.path.join(case_dir, f))]
    return ", ".join(files)

def remove_files(directory: str, prefix: str) -> None:
    for file in os.listdir(directory):
        if file.startswith(prefix):
            os.remove(os.path.join(directory, file))
    logger.info(f"Removed files with prefix '{prefix}' in {directory}")

def remove_file(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Removed file {path}")

def remove_numeric_folders(case_dir: str) -> None:
    """
    Remove all folders in case_dir that represent numeric values, including those with decimal points,
    except for the "0" folder.
    
    Args:
        case_dir (str): The directory path to process
    """
    for item in os.listdir(case_dir):
        item_path = os.path.join(case_dir, item)
        if os.path.isdir(item_path) and item != "0":
            try:
                # Try to convert to float to check if it's a numeric value
                float(item)
                # If conversion succeeds, it's a numeric folder
                try:
                    shutil.rmtree(item_path)
                    logger.info(f"Removed numeric folder: {item_path}")
                except Exception as e:
                    logger.error(f"Error removing folder {item_path}: {str(e)}")
            except ValueError:
                # Not a numeric value, so we keep this folder
                pass


def scan_case_directory(case_dir: str) -> Dict[str, List[str]]:
    """
    Scan an OpenFOAM case directory and return the directory structure.
    
    This function traverses the case directory one level deep and collects
    the files in each subdirectory (typically 'system', 'constant', '0', etc.).
    
    Args:
        case_dir (str): Path to the OpenFOAM case directory
    
    Returns:
        Dict[str, List[str]]: Dictionary mapping folder names to lists of file names
            Example: {"system": ["controlDict", "fvSchemes"], "constant": ["transportProperties"]}
    
    Raises:
        FileNotFoundError: If case_dir does not exist
        PermissionError: If directory cannot be accessed
    
    Example:
        >>> structure = scan_case_directory("/path/to/case")
        >>> logger.info(structure["system"])  # ["controlDict", "fvSchemes", "fvSolution"]
    """
    if not os.path.exists(case_dir):
        raise FileNotFoundError(f"Case directory does not exist: {case_dir}")
    
    dir_structure = {}
    base_depth = case_dir.rstrip(os.sep).count(os.sep)
    
    # Walk through the directory tree
    for root, dirs, files in os.walk(case_dir):
        # Only process directories one level below case_dir
        current_depth = root.rstrip(os.sep).count(os.sep)
        if current_depth == base_depth + 1:
            folder_name = os.path.relpath(root, case_dir)
            # Filter out hidden files and only include regular files
            regular_files = [f for f in files if not f.startswith('.') and os.path.isfile(os.path.join(root, f))]
            if regular_files:
                dir_structure[folder_name] = regular_files
    
    return dir_structure


def read_case_foamfiles(case_dir: str, dir_structure: Optional[Dict[str, List[str]]] = None) -> 'FoamPydantic':
    """
    Read OpenFOAM files from a case directory and convert to FoamPydantic format.
    
    This function reads all OpenFOAM configuration files from the case directory
    (typically from 'system', 'constant', '0' folders) and creates a FoamPydantic
    object containing the file contents.
    
    Args:
        case_dir (str): Path to the OpenFOAM case directory
        dir_structure (Optional[Dict[str, List[str]]]): Pre-scanned directory structure.
            If None, will scan the directory automatically.
    
    Returns:
        FoamPydantic: Object containing list of FoamfilePydantic objects with file metadata
    
    Raises:
        FileNotFoundError: If case_dir does not exist
        UnicodeDecodeError: If files contain invalid encoding (will skip those files)
    
    Example:
        >>> foamfiles = read_case_foamfiles("/path/to/case")
        >>> logger.info(len(foamfiles.list_foamfile))  # Number of files read
        >>> logger.info(foamfiles.list_foamfile[0].file_name)  # "controlDict"
    """
    if not os.path.exists(case_dir):
        raise FileNotFoundError(f"Case directory does not exist: {case_dir}")
    
    # Scan directory structure if not provided
    if dir_structure is None:
        dir_structure = scan_case_directory(case_dir)
    
    foamfile_list = []
    
    # Read files from each folder
    for folder_name, file_names in dir_structure.items():
        for file_name in file_names:
            file_path = os.path.join(case_dir, folder_name, file_name)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                foamfile_list.append(FoamfilePydantic(
                    file_name=file_name,
                    folder_name=folder_name,
                    content=content
                ))
            except UnicodeDecodeError:
                logger.warning(f"Warning: Skipping file due to encoding error: {file_path}")
            except Exception as e:
                logger.warning(f"Warning: Error reading file {file_path}: {e}")
    
    return FoamPydantic(list_foamfile=foamfile_list)

def run_command(script_path: str, out_file: str, err_file: str, working_dir: str, max_time_limit: int) -> None:
    """Execute an OpenFOAM shell script, writing its output to the given files.

    Which OpenFOAM the script sees -- the one on this machine or the one in a container --
    is the execution backend's decision; see foamagent.execution.
    """
    logger.info(f"Executing script {script_path} in {working_dir}")
    os.chmod(script_path, 0o777)

    backend = get_execution_backend()
    result = backend.run(
        ["bash", os.path.abspath(script_path)],
        working_dir,
        timeout=max_time_limit,
    )

    stdout, stderr = result.stdout, result.stderr
    if result.timed_out:
        timeout_message = (
            "OpenFOAM execution took too long. "
            "This case, if set up right, does not require such large execution times.\n"
        )
        stdout = timeout_message + stdout
        stderr = timeout_message + stderr
        logger.info(f"Execution timed out: {script_path}")

    with open(out_file, 'w') as out, open(err_file, 'w') as err:
        out.write(stdout)
        err.write(stderr)

    logger.info(f"Executed script {script_path}")

def check_foam_errors(directory: str) -> list:
    """Check OpenFOAM log files for errors.

    Tier 1 (existing): Match explicit ``ERROR:`` lines.
    Tier 2 (safety-net): If no explicit error is found, verify that **every**
    log file contains the ``End`` marker that OpenFOAM prints on successful
    completion.  Any log missing ``End`` is reported with the last 30 lines
    as error context so the caller can diagnose the crash.
    """
    error_logs = []
    log_contents = {}  # filename -> content

    # DOTALL mode allows '.' to match newline characters
    pattern = re.compile(r"ERROR:(.*)", re.DOTALL)

    for file in os.listdir(directory):
        if file.startswith("log"):
            filepath = os.path.join(directory, file)
            try:
                with open(filepath, 'r') as f:
                    content = f.read()
            except (IOError, OSError):
                error_logs.append({"file": file, "error_content": f"Could not read log file: {filepath}"})
                continue

            log_contents[file] = content

            match = pattern.search(content)
            if match:
                error_content = match.group(0).strip()
                error_logs.append({"file": file, "error_content": error_content})
            elif "error" in content.lower():
                logger.warning(f"Warning: file {file} contains 'error' but does not match expected format.")

    # Safety-net: if no explicit ERROR was found, check for missing 'End' marker
    # Check EACH log individually – a successful blockMesh should not mask a
    # crashed solver (e.g. pimpleFoam).
    if not error_logs and log_contents:
        end_pattern = re.compile(r"^\s*End\s*$", re.MULTILINE)

        for file, content in log_contents.items():
            if not end_pattern.search(content):
                last_lines = "\n".join(content.strip().split("\n")[-30:])
                error_logs.append({
                    "file": file,
                    "error_content": (
                        f"Solver did not complete (no 'End' marker found). "
                        f"Last 30 lines:\n{last_lines}"
                    ),
                })

    return error_logs

def extract_commands_from_allrun_out(out_file: str) -> list:
    commands = []
    if not os.path.exists(out_file):
        return commands
    with open(out_file, 'r') as f:
        for line in f:
            if line.startswith("Running "):
                parts = line.split(" ")
                if len(parts) > 1:
                    commands.append(parts[1].strip())
    return commands

def parse_case_name(text: str) -> str:
    match = re.search(r'case name:\s*(.+)', text, re.IGNORECASE)
    return match.group(1).strip() if match else "default_case"

def split_subtasks(text: str) -> list:
    header_match = re.search(r'splits into (\d+) subtasks:', text, re.IGNORECASE)
    if not header_match:
        logger.warning("Warning: No subtasks header found in the response.")
        return []
    num_subtasks = int(header_match.group(1))
    subtasks = re.findall(r'subtask\d+:\s*(.*)', text, re.IGNORECASE)
    if len(subtasks) != num_subtasks:
        logger.warning(f"Warning: Expected {num_subtasks} subtasks but found {len(subtasks)}.")
    return subtasks

def parse_context(text: str) -> str:
    match = re.search(r'FoamFile\s*\{.*?(?=```|$)', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()
    
    logger.warning("Warning: Could not parse context; returning original text.")
    return text


def parse_file_name(subtask: str) -> str:
    match = re.search(r'openfoam\s+(.*?)\s+foamfile', subtask, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def parse_folder_name(subtask: str) -> str:
    match = re.search(r'foamfile in\s+(.*?)\s+folder', subtask, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def find_similar_file(description: str, tutorial: str) -> str:
    start_pos = tutorial.find(description)
    if start_pos == -1:
        return "None"
    end_marker = "input_file_end."
    end_pos = tutorial.find(end_marker, start_pos)
    if end_pos == -1:
        return "None"
    return tutorial[start_pos:end_pos + len(end_marker)]

def read_commands(file_path: str) -> str:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Commands file not found: {file_path}")
    with open(file_path, 'r') as f:
        # join non-empty lines with a comma
        return ", ".join(line.strip() for line in f if line.strip())

def find_input_file(case_dir: str, command: str) -> str:
    for root, _, files in os.walk(case_dir):
        for file in files:
            if command in file:
                return os.path.join(root, file)
    return ""

def retrieve_faiss(database_name: str, query: str, topk: int = 1) -> dict:
    """Retrieve references from the OpenFOAM corpus.

    Kept under its original name for callers outside this package. Which method answers is
    now the retrieval layer's decision, not this function's -- despite the name, it is not
    necessarily FAISS. New code should call foamagent.retrieval.retrieve.
    """
    from foamagent.retrieval import retrieve

    return retrieve(database_name, query, topk)


def parse_directory_structure(data: str) -> dict:
    """
    Parses the directory structure string and returns a dictionary where:
      - Keys: directory names
      - Values: count of files in that directory.
    """
    directory_file_counts = {}

    # Find all <dir>...</dir> blocks in the input string.
    dir_blocks = re.findall(r'<dir>(.*?)</dir>', data, re.DOTALL)

    for block in dir_blocks:
        # Extract the directory name (everything after "directory name:" until the first period)
        dir_name_match = re.search(r'directory name:\s*(.*?)\.', block)
        # Extract the list of file names within square brackets
        files_match = re.search(r'File names in this directory:\s*\[(.*?)\]', block)
        
        if dir_name_match and files_match:
            dir_name = dir_name_match.group(1).strip()
            files_str = files_match.group(1)
            # Split the file names by comma, removing any surrounding whitespace
            file_list = [filename.strip() for filename in files_str.split(',')]
            directory_file_counts[dir_name] = len(file_list)

    return directory_file_counts
