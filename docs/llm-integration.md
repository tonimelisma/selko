# LLM Integration — Multi-Provider Architecture

## Overview

Selko uses a provider-agnostic LLM abstraction layer (`LLMProvider` + `LLMGateway`) that supports 8 providers and 37 models. The application default is Anthropic Claude Sonnet 5, but any registered provider/model can be selected via `LLM_PROVIDER` and `LLM_MODEL`.

### Supported Providers

| Provider | Env Var Key | Default Model | Vision |
|----------|-------------|---------------|--------|
| Gemini | `GEMINI_API_KEY` | `gemini-3-flash-preview` | Yes |
| Moonshot (Kimi) | `MOONSHOT_API_KEY` | `kimi-k2.6` | Yes |
| ZAI (GLM) | `ZAI_API_KEY` | `glm-5.2` | Yes |
| Qwen | `ALIBABA_API_KEY` | `qwen3.5-flash` | Yes |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` | No |
| MiniMax | `MINIMAX_API_KEY` | `MiniMax-M2.5` | No |
| OpenAI | `OPENAI_API_KEY` | `gpt-5.6-sol` | Yes |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-5` | Yes |

See `backend/selko/services/llm_provider.py` for the full `MODEL_REGISTRY` with pricing, context windows, and capabilities.

## Gemini-Specific Setup

The following section covers Google Gemini setup.

## **Executive Summary**

The enterprise technology landscape is currently witnessing a fundamental architectural convergence where distinct disciplines—communication protocol handling, computer vision, and semantic analysis—are merging into unified generative workflows. For developers utilizing the Google Cloud Platform (GCP), this shift is epitomized by the transition from specialized, disparate APIs (such as the Cloud Vision API or Natural Language API) to generalized, multimodal foundation models like Gemini. The objective of this report is to provide an exhaustive technical blueprint for constructing a high-performance pipeline capable of analyzing email contents, classifying attached imagery, and extracting structured data using Python.  
The request to integrate email analysis with the latest Gemini models highlights a specific and sophisticated intersection of technologies: the ingestion of legacy communication protocols (Gmail) and their synthesis with state-of-the-art generative artificial intelligence. This requires navigating a rapidly evolving software development kit (SDK) ecosystem, where Google has recently deprecated legacy libraries in favor of a unified google-genai SDK. This report argues that the successful implementation of such a system relies not merely on model selection, but on a rigorous adherence to modern authentication protocols (OAuth 2.0 coupled with IAM), efficient in-memory data handling to minimize input/output (I/O) latency, and the enforcement of deterministic outputs via Pydantic integration.  
The analysis that follows establishes that the optimal path for this implementation involves the google-genai Python library, configured to backend services via the Vertex AI API.1 It necessitates a hybrid authentication strategy where user credentials, authorized for Gmail access, are seamlessly propagated to Vertex AI contexts.3 Furthermore, it demonstrates that "image classification" in the generative era is best conceptually framed as a structured extraction task, leveraging the "JSON Mode" capabilities of Gemini 2.0 and 2.5 to produce strictly typed classification enums rather than unstructured conversational text.4

## ---

**Part I: The Google AI Ecosystem Transformation**

To understand the correct libraries and APIs required for this project, one must first navigate the complex and recently restructured history of Google’s Python client libraries. The confusion often experienced by developers stems from the existence of parallel toolchains that are now being consolidated.

### **1.1 The Great SDK Migration: google-genai vs. google-cloud-aiplatform**

Historically, Google maintained two distinct software lineages for its generative AI products, creating a bifurcated developer experience. On one side was google-generativeai (importing as genai), designed solely for the Gemini Developer API—a rapid prototyping environment primarily for hobbyists and individual developers using API keys. On the other side was google-cloud-aiplatform (importing as vertexai), a heavy enterprise-grade library deeply integrated with Google Cloud’s MLOps infrastructure.2  
This dichotomy forced developers to make a hard choice early in the project lifecycle: optimize for ease of use (Developer API) or robust infrastructure (Vertex AI). Migrating between the two required significant code refactoring, as the method signatures for generating content and handling responses differed fundamentally.

#### **The Unified Future: google-genai**

The definitive solution for modern development, and the primary recommendation for this report, is the adoption of the **Google Gen AI SDK**, distributed on PyPI as google-genai. Released in late 2024 to coincide with the Gemini 2.0 series, this library represents a unified interface that abstracts the underlying backend.1  
**Strategic Advantages of google-genai:**

1. **Backend Agnosticism:** The SDK introduces a client architecture where the backend—whether the Developer API or Vertex AI—is determined by configuration flags rather than distinct library imports. This allows the same codebase to run in a local prototype environment or a secure VPC-SC (Virtual Private Cloud Service Controls) production environment with minimal changes.1  
2. **Version Compatibility:** The google-genai SDK is the primary vehicle for accessing the latest model iterations, including Gemini 2.0 Flash and Gemini 2.5 Pro. Legacy SDKs, particularly the generative modules within google-cloud-aiplatform, have been marked for deprecation and will effectively cease to receive new generative features by 2026\.2  
3. **Modern Python Paradigms:** Unlike its predecessors, which relied heavily on loose dictionaries and Protocol Buffers, google-genai embraces modern Python typing. It offers first-class support for Pydantic models, allowing for the definitions of input and output schemas that are critical for the data extraction requirements of this project.4

**Table 1: Comparison of Python Client Libraries for Google AI**

| Feature | google-generativeai (Legacy) | google-cloud-aiplatform (Legacy) | google-genai (Recommended) |
| :---- | :---- | :---- | :---- |
| **Primary Import** | import google.generativeai | import vertexai | from google import genai |
| **Backend Support** | Developer API only | Vertex AI only | **Both** (Unified) |
| **Gemini 2.5 Support** | Limited / Lagging | Limited | **Day 1 Support** |
| **Structured Output** | Basic JSON Schema | Dictionary-based | **Pydantic / Native Python Types** |
| **Async Support** | Partial | Yes | **Full (.aio access)** |
| **Deprecation Status** | Maintenance Mode | Generative module deprecated | **Active / Strategic Standard** |

### **1.2 API Selection and Enabling Services**

The user query implies an existing Google Cloud Project. To orchestrate the requested pipeline—analyzing emails via Gmail and processing them with Gemini—specific Google Cloud APIs must be actively enabled in the project console. The distinction between the *control plane* (interacting with Google Cloud resources) and the *data plane* (sending prompts to models) is critical here.

#### **The Vertex AI API (aiplatform.googleapis.com)**

While the Gemini Developer API offers a quick start via Google AI Studio, the requirement to integrate with an existing OAuth app and Google Cloud Project dictates the use of the **Vertex AI API**. Vertex AI provides the enterprise infrastructure required for higher rate limits, data residency guarantees, and integration with IAM (Identity and Access Management). Unlike the Developer API, which uses simple API keys, Vertex AI expects OAuth 2.0 tokens, aligning perfectly with the user's existing Gmail authentication setup.9  
**Mechanism of Action:**  
Enabling this API spins up the necessary service agents (managed identities) within the Google Cloud Project that handle the orchestration of model inference requests. It allows the project to consume the quota for Gemini models.

#### **The Gmail API (gmail.googleapis.com)**

For fetching email data, the Gmail API is the standard interface. It allows for granular retrieval of messages and attachments without the overhead of the legacy IMAP protocol. It provides a RESTful interface to the user's mailbox, supporting complex queries and efficient binary retrieval.11

#### **The Service Usage API (serviceusage.googleapis.com)**

Often overlooked, the **Service Usage API** must be enabled. It is the meta-API that allows the client library to check the status of *other* APIs and ensure that quotas are being respected. Failures here often manifest as opaque "Project not found" or "API not enabled" errors during client initialization.9  
**Implementation Directive:**  
The developer must execute the following command (or perform the equivalent action in the Cloud Console) to ensure the environment is ready:

Bash

gcloud services enable aiplatform.googleapis.com gmail.googleapis.com serviceusage.googleapis.com

## ---

**Part II: Identity, Access, and Security Architecture**

The architectural constraints provided—"I already have an OAuth app for accessing Gmail APIs"—create a specific and somewhat non-standard authentication requirement for server-side AI analysis. Most Vertex AI documentation assumes the use of a Service Account (a machine identity). However, accessing a user's *personal* Gmail data typically requires **User Credentials** (3-legged OAuth), as a Service Account cannot access a user's private inbox unless Domain-Wide Delegation is configured (which is rare for individual use cases and restricted in many organizations).

### **2.1 The User vs. Service Account Dilemma**

In a standard enterprise deployment, an application uses a Service Account to talk to Vertex AI. However, this application needs to read the *user's* email. If the application uses the Service Account for everything, it fails to read the email. If it uses the User's credentials for everything, it might fail to talk to Vertex AI if the user lacks cloud permissions.  
The solution is a **Unified Credential Strategy**. The google-genai SDK is uniquely architected to handle this scenario by allowing the explicit injection of user credentials into the Vertex AI client. This means the same OAuth token obtained to read the user's emails can be used to authorize the AI analysis requests, provided the scopes are correct.3

### **2.2 Configuring OAuth Scopes and IAM Roles**

The security model relies on two layers: **OAuth Scopes** (what the app requests permission to do) and **IAM Roles** (what the user is actually allowed to do in the cloud project).

#### **Layer 1: OAuth Scopes**

The OAuth 2.0 flow must request a composite scope that covers both the data source (Gmail) and the processing engine (Google Cloud Platform). The application must request:

1. https://www.googleapis.com/auth/gmail.readonly: This grants least-privilege access to read emails and attachments. It is preferred over gmail.modify or gmail.compose to minimize the security blast radius.11  
2. https://www.googleapis.com/auth/cloud-platform: This is the master scope that allows the credentials to interact with Google Cloud APIs, including Vertex AI. Note that while this scope is broad, the actual actions allowed are limited by the second layer (IAM).13

#### **Layer 2: IAM Role Assignment**

Possessing a valid OAuth token with cloud-platform scope is insufficient if the underlying user identity does not have permission to invoke Vertex AI models. The Google Account associated with the OAuth credentials must be granted specific roles within the Google Cloud Project.

* **Vertex AI User (roles/aiplatform.user):** This is the critical role. It grants permission to predict (inference) and use generative models. It does *not* grant permission to modify the project structure or view other resources, enforcing the principle of least privilege.9  
* **Service Usage Consumer (roles/serviceusage.serviceUsageConsumer):** This role allows the user's requests to bill against the project's quota. Without this, the API calls may be rejected even if the user has Vertex AI permissions.9

### **2.3 Client Initialization with Explicit Credentials**

The google-genai SDK simplifies the integration of these credentials. Unlike previous generations where setting up a custom session or request object was required, the new Client constructor accepts a credentials object directly.

Python

from google import genai  
from google.oauth2.credentials import Credentials

\# 'creds' is the google.oauth2.credentials.Credentials object   
\# obtained from the initial 3-legged OAuth flow for Gmail.

client \= genai.Client(  
    vertexai=True,  
    project="YOUR\_PROJECT\_ID",  
    location="us-central1",  
    credentials=creds  
)

**Architectural Insight:** By passing vertexai=True, we force the SDK to route requests through the us-central1-aiplatform.googleapis.com endpoint (or other regional endpoints) rather than the public generativelanguage.googleapis.com. This ensures the request is handled within the compliance and quota boundary of the user's project.6

### **2.4 Environment Configuration vs. Programmatic Injection**

While the client supports programmatic injection as shown above, managing configuration via environment variables is a robust pattern for attributes that do not change per-request (like Project ID).

* GOOGLE\_CLOUD\_PROJECT: The project ID.  
* GOOGLE\_CLOUD\_LOCATION: The region (e.g., us-central1).  
* GOOGLE\_GENAI\_USE\_VERTEXAI: Setting this to true allows for zero-argument client instantiation (client \= genai.Client()) if Application Default Credentials are used, though explicitly passing the user credentials remains necessary for this specific Gmail-linked architecture.1

## ---

**Part III: The Data Ingestion Layer (Gmail API Mechanics)**

The first operational stage of the pipeline is retrieving the unstructured data. The complexity here lies in efficiently parsing the MIME (Multipurpose Internet Mail Extensions) structure of emails to locate relevant text and image attachments without unnecessary disk I/O or latency.

### **3.1 Fetching Messages: REST vs. Transcoding**

The google-api-python-client (specifically the discovery.build function) remains the standard tool for the Gmail API. While the google-genai library handles the AI, it does not replace the Gmail client.  
**The List-Then-Get Pattern:**  
The Gmail API operations are bifurcated. One cannot simply "download all emails."

1. **List:** The users().messages().list() method is used to retrieve a list of message IDs. This method supports a powerful query syntax (q) that filters processing upstream.  
   * *Optimization:* Use q="has:attachment newer\_than:1d" to filter for emails that actually contain potential images, drastically reducing the number of API calls.17  
2. **Get:** The users().messages().get() method retrieves the actual content. The format='full' parameter is essential here to retrieve the payload parts required for attachment analysis.

### **3.2 Recursive MIME Parsing and Attachment Retrieval**

Modern emails are complex trees of data. A single email might contain a multipart/mixed root, containing a multipart/alternative branch (holding the text and HTML versions of the body), and separate branches for attachments.  
**The Attachment Handling Protocol:**  
When users().messages().get() returns the email structure, the actual binary data of large attachments is *not* included. Instead, the response contains an attachmentId. To get the image, a third API call is required: users().messages().attachments().get().  
**Critical Implementation Detail:**  
The Gmail API returns binary data as a **Base64URL** encoded string. This is distinct from standard Base64.

* Standard Base64 uses \+ and /.  
* Base64URL uses \- and \_.  
* **The Fix:** The Python base64 library's urlsafe\_b64decode method must be used. Attempting to use standard decode will result in corruption or padding errors.19

### **3.3 In-Memory Byte Streams: Security and Performance**

A common anti-pattern in data science pipelines is to download an attachment, save it to a temporary file on disk (e.g., /tmp/image.jpg), and then read it back to pass to the model.  
**Architectural Recommendation: In-Memory Processing**  
The google-genai SDK supports passing raw bytes directly to the model. This offers two massive advantages:

1. **Latency Reduction:** It eliminates the I/O overhead of writing and reading from the disk.  
2. **Security Compliance:** In rigorous enterprise environments, writing user data (email attachments) to disk—even temporarily—can violate data handling policies (e.g., GDPR, HIPAA). Keeping the data in volatile memory (RAM) ensures it exists only for the duration of the analysis process.

The pipeline should utilize io.BytesIO streams if stream manipulation is needed, or simply pass the bytes object returned by the decoder directly to the Gemini SDK's types.Part.from\_bytes constructor.21

## ---

**Part IV: Multimodal Input Engineering**

With the raw data extracted from Gmail, the next challenge is bridging the gap between binary data and the semantic understanding of the Gemini model. This section details the multimodal interface of the google-genai SDK.

### **4.1 How Gemini "Sees" Data**

Gemini is a natively multimodal model. This means it was trained on interleaved text, images, and video. When an image is passed to the model, it is not "captioned" by a separate process and then fed as text; rather, the image is tokenized into visual tokens that sit in the context window alongside the text tokens.  
**Token Consumption:** In the Gemini 1.5 and 2.0 architectures, a standard image consumes approximately **258 tokens**, regardless of its resolution (up to a limit, after which it is tiled). This efficiency allows for the analysis of multiple attachments—for example, analyzing a thread with 10 attached invoices—in a single request.22

### **4.2 constructing the Multimodal Request**

The google-genai SDK simplifies the construction of these mixed-media prompts. The core abstraction is the Part. A request consists of a list of Content objects, each containing a list of Part objects.

Python

from google.genai import types

\# 'image\_bytes' is the raw data decoded from Gmail  
image\_part \= types.Part.from\_bytes(  
    data=image\_bytes,  
    mime\_type="image/jpeg"  \# Must match the email attachment's Content-Type  
)

text\_part \= types.Part.from\_text("Analyze this email attachment for anomalies.")

\# The unified content payload  
contents \= \[text\_part, image\_part\]

**Handling MIME Types:** The MIME type passed to from\_bytes is critical. Gemini uses this to trigger the correct encoder (e.g., the video encoder vs. the image encoder). The Gmail API provides the MIME type in the message payload headers (e.g., image/jpeg, application/pdf). This metadata must be propagated accurately to the Gemini Part to avoid "Invalid Argument" errors.21

### **4.3 Limits and the File API**

While the in-memory approach is superior for speed, it has a hard limit. The total request size (JSON payload including Base64 strings) is limited to **20MB** for the Vertex AI API.  
**Alternative Strategy for Large Assets:**  
If the email contains a large video file or a high-resolution PDF exceeding 20MB, the in-memory approach will fail. In such cases, the pipeline must implement a fallback:

1. Upload the bytes to the **Gemini File API** (for Developer API backend) or **Google Cloud Storage** (for Vertex AI backend).  
2. Pass the file\_uri (e.g., gs://bucket/object) to the model instead of the raw bytes. However, for standard email image analysis (receipts, photos, screenshots), the 20MB limit is rarely breached, making the inline from\_bytes method the default recommendation.21

## ---

**Part V: Deterministic Output and Pydantic Integration**

The user's requirement includes "data extraction." In the era of Large Language Models (LLMs), relying on natural language prompts (e.g., "Please list the date and total") is architecturally fragile. The model might return Markdown formatting, conversational filler ("Sure, here is the data..."), or inconsistent date formats (DD/MM/YYYY vs MM/DD/YYYY).  
To build a reliable system, we must enforce **Structured Outputs**.

### **5.1 The Pydantic Revolution**

The google-genai SDK introduces a transformative feature: direct integration with **Pydantic**. Pydantic is the standard data validation library for Python. It allows developers to define the *shape* of data as a Python class.  
**Why Pydantic?**

* **Type Safety:** It guarantees that if the model extracts a "Total Amount," it is returned to the Python environment as a float, not a string like "$100.00".  
* **Validation:** Pydantic performs client-side validation immediately upon receiving the response.  
* **Schema Generation:** The SDK automatically transpiles the Pydantic class into the complex JSON Schema required by the Gemini API, saving the developer from writing verbose and error-prone JSON definitions.4

### **5.2 Classification as Extraction**

The user requested "image classification." In traditional Machine Learning, this involves training a bespoke CNN (Convolutional Neural Network) on labeled data. With Gemini, classification is simply a specific type of structured extraction where the target field is an **Enumeration (Enum)**.  
By defining a Python Enum, we constrain the model's output to a strict set of values. The model cannot hallucinate a new category; it must choose the best fit from the provided options.  
**Table 2: Traditional ML vs. GenAI Classification**

| Feature | Traditional ML (e.g., ResNet) | GenAI Classification (Gemini \+ Pydantic) |
| :---- | :---- | :---- |
| **Training Data** | Requires thousands of labeled images | Zero-shot (uses pre-trained knowledge) |
| **Flexibility** | Rigid; changing categories requires retraining | Fluid; changing categories requires editing the Enum |
| **Context** | Sees only the image | Sees the image *and* the email body text |
| **Output** | Probability score (0.0 \- 1.0) | Semantic label (e.g., "INVOICE") |

### **5.3 Implementing the Schema**

The implementation involves defining a BaseModel that encapsulates the desired analysis.

Python

from pydantic import BaseModel, Field  
from enum import Enum  
from typing import List

class DocumentCategory(str, Enum):  
    INVOICE \= "invoice"  
    LEGAL \= "legal"  
    PERSONAL \= "personal"  
    SPAM \= "spam"

class EmailAnalysis(BaseModel):  
    category: DocumentCategory \= Field(description="The classification of the email and attachment.")  
    summary: str \= Field(description="A concise summary of the content.")  
    entities: List\[str\] \= Field(description="Names of people or companies mentioned.")  
    requires\_action: bool \= Field(description="True if the email requires a reply.")

When this class is passed to the response\_schema parameter of the generate\_content configuration, the SDK handles the serialization and deserialization transparently. The return value from the API call is an instance of EmailAnalysis, ready for use in downstream Python logic.25

### **5.4 response\_schema vs. response\_json\_schema**

A technical nuance in the google-genai SDK is the distinction between schema parameters.

* **response\_schema**: This parameter is optimized for Pydantic integration. When passing a Pydantic class, this is the correct field to use.  
* **response\_json\_schema**: This field is used when passing a raw JSON Schema dictionary (e.g., derived from a separate schema registry). Using the wrong parameter can result in validation errors or the model ignoring the constraints. For this pipeline, response\_schema is the strictly correct choice.26

## ---

**Part VI: Pipeline Orchestration and Optimization**

Having defined the components—Auth, Ingestion, Multimodal Processing, and Extraction—this section focuses on operationalizing the pipeline for performance, cost, and reliability.

### **6.1 Model Selection Strategy: The Cost/Performance Trade-off**

Gemini offers multiple variants. Choosing the right one is a balance of latency, cost, and reasoning depth.

1. **Gemini 1.5 Pro:** Features a massive context window (2M tokens) and deep reasoning. It is ideal for analyzing very long email threads with dozens of attachments or complex legal documents. However, it is higher latency and cost.  
2. **Gemini 2.0 Flash:** The "workhorse" model. It is significantly faster and cheaper than Pro. For standard email classification and data extraction (e.g., reading a receipt), it is the optimal choice.  
3. **Gemini 2.5:** The newest iteration, offering enhanced coding and reasoning capabilities. While powerful, its availability may vary by region during the rollout phase.1

**Recommendation:** Default to **Gemini 2.0 Flash** (gemini-2.0-flash-001). Implement a "cascading" fallback: if Flash returns a "Low Confidence" flag (which you can add to your Pydantic model), retry the specific difficult email with Gemini 1.5 Pro.

### **6.2 Asynchronous Processing for High Throughput**

Email analysis is fundamentally an I/O-bound operation. The system spends most of its time waiting: waiting for Gmail to fetch the attachment, and waiting for Gemini to generate the token stream. Running this synchronously (one email after another) is inefficient.  
The google-genai SDK exposes an asynchronous client via the .aio attribute.

* **Pattern:** await client.aio.models.generate\_content(...).  
* **Benefit:** This allows the Python event loop to fetch the *next* email from Gmail while the *current* email is being analyzed by Vertex AI. This pipelining can increase throughput by an order of magnitude without increasing compute resources.6

### **6.3 Safety Settings and Error Handling**

Generative models include safety filters to block hate speech, harassment, and sexually explicit content. When processing emails, which may contain spam or contentious language, these filters can trigger false positives, resulting in the API returning a FinishReason.SAFETY instead of the extracted data.  
**Operational Tactic:** For an automated backend process, you should explicitly configure the safety\_settings to BLOCK\_ONLY\_HIGH or BLOCK\_NONE (if permitted by organizational policy). This ensures the model processes the content and returns the classification (e.g., classifying it as "SPAM" or "ABUSIVE") rather than silently failing. This moves the decision logic from the opaque model filter to your transparent application logic.28

## ---

**Conclusion**

The implementation of an email analysis and image classification system using Gemini on Google Cloud represents a shift from imperative programming (writing rules to parse text) to declarative intent (describing the schema of the desired output). The convergence of the google-genai SDK, the Vertex AI API, and Pydantic creates a powerful toolchain that is both flexible and robust.  
The critical success factors identified in this report are:

1. **Unified SDK Adoption:** Utilizing google-genai to future-proof the application and simplify the codebase.  
2. **Hybrid Auth:** Correctly propagating OAuth user credentials to the Vertex AI client to bridge the gap between Gmail data privacy and Cloud compute permissions.  
3. **In-Memory Efficiency:** minimizing I/O overhead by passing byte streams directly to the multimodal context window.  
4. **Schema Enforcement:** treating classification and extraction not as conversational tasks, but as strict data serialization tasks using Pydantic.

By adhering to this architectural blueprint, developers can deploy a system that is not only capable of understanding the nuance of human communication but is also reliable enough to drive downstream business automation.

## **Detailed Technical Addendum: Code Integration Reference**

This section provides a synthesized reference implementation, demonstrating how the architectural concepts interact at the code level.

### **1\. Pydantic Schema Definition**

This defines the "contract" for the extraction, effectively programming the model's output behavior.

Python

from pydantic import BaseModel, Field  
from enum import Enum  
from typing import List

\# Define the classification categories as an Enum to enforce rigid output.  
class AttachmentCategory(str, Enum):  
    INVOICE \= "invoice"  
    RECEIPT \= "receipt"  
    CONTRACT \= "contract"  
    PROMOTIONAL \= "promotional"  
    UNKNOWN \= "unknown"

\# Define the master schema for the analysis result.  
class EmailAnalysis(BaseModel):  
    summary: str \= Field(  
        description="A concise 2-sentence summary of the email content and attachment."  
    )  
    category: AttachmentCategory \= Field(  
        description="The precise classification of the attached image."  
    )  
    \# Optional fields handle cases where data is missing without breaking the pipeline.  
    total\_amount: float | None \= Field(  
        description="If an invoice or receipt, the total amount found. Otherwise null.",  
        default=None  
    )  
    \# List extraction is handled natively.  
    action\_items: List\[str\] \= Field(  
        description="A list of specific actions required by the recipient."  
    )

### **2\. Client Initialization (Unified Backend)**

This function bridges the OAuth user identity with the Vertex AI infrastructure, handling the credential injection.

Python

from google import genai  
from google.genai import types

def get\_vertex\_client(oauth\_credentials):  
    """  
    Initializes the Gemini client using existing OAuth credentials.  
      
    Args:  
        oauth\_credentials: The google.oauth2.credentials.Credentials object   
                           authorized for 'cloud-platform' scope.  
    """  
    return genai.Client(  
        vertexai=True,  
        project="your-project-id",  \# Replace with actual Project ID  
        location="us-central1",     \# Vertex AI region  
        credentials=oauth\_credentials  
    )

### **3\. Multimodal Execution Logic**

This core function demonstrates the in-memory byte passing and the invocation of the structured generation config.

Python

def analyze\_email\_multimodal(client, email\_text, image\_bytes, mime\_type):  
    """  
    Performs multimodal analysis on email text and an in-memory image.  
    """  
    \# 1\. Construct the Multimodal Prompt  
    \# We pass the raw bytes directly. The SDK handles Base64 encoding for the API.  
    image\_part \= types.Part.from\_bytes(  
        data=image\_bytes,  
        mime\_type=mime\_type  
    )  
    text\_part \= types.Part.from\_text(email\_text)  
      
    \# 2\. Configure the Generation  
    \# We enforce the Pydantic schema here using 'response\_schema'.  
    generate\_config \= types.GenerateContentConfig(  
        response\_mime\_type="application/json",  
        response\_schema=EmailAnalysis,   
        temperature=0.1  \# Low temperature reduces hallucination for extraction  
    )

    \# 3\. Invoke the Model (Gemini 2.0 Flash for speed)  
    response \= client.models.generate\_content(  
        model="gemini-2.0-flash-001",  
        contents=\[text\_part, image\_part\],  
        config=generate\_config  
    )  
      
    \# 4\. Return the Parsed Pydantic Object  
    \# The SDK automatically validates the JSON against the schema.  
    return response.parsed 

This code structure embodies the modern best practices advocated throughout this report, ensuring type safety, security compliance, and architectural efficiency.

#### **Works cited**

1. Google Gen AI SDK | Generative AI on Vertex AI \- Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview)  
2. Good Bye Vertex AI SDK \- minherz: another techno-blog, accessed January 21, 2026, [https://leoy.blog/posts/good-bye-vertex-ai-sdk/](https://leoy.blog/posts/good-bye-vertex-ai-sdk/)  
3. Authenticate to Vertex AI | Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/vertex-ai/docs/authentication](https://docs.cloud.google.com/vertex-ai/docs/authentication)  
4. Improving Structured Outputs in the Gemini API \- Google Blog, accessed January 21, 2026, [https://blog.google/innovation-and-ai/technology/developers-tools/gemini-api-structured-outputs/](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-api-structured-outputs/)  
5. Differences in Response Models between the Vertex AI SDK and the Gen AI SDK \- DEV Community, accessed January 21, 2026, [https://dev.to/polar3130/differences-in-response-models-between-the-vertex-ai-sdk-and-the-gen-ai-sdk-4m49](https://dev.to/polar3130/differences-in-response-models-between-the-vertex-ai-sdk-and-the-gen-ai-sdk-4m49)  
6. Google Gen AI SDK documentation \- googleapis.github.io, accessed January 21, 2026, [https://googleapis.github.io/python-genai/](https://googleapis.github.io/python-genai/)  
7. Migrate to the Google GenAI SDK | Gemini API, accessed January 21, 2026, [https://ai.google.dev/gemini-api/docs/migrate](https://ai.google.dev/gemini-api/docs/migrate)  
8. Google Gen AI Python SDK: A Complete Guide \- Analytics Vidhya, accessed January 21, 2026, [https://www.analyticsvidhya.com/blog/2025/08/google-gen-ai-python-sdk-guide/](https://www.analyticsvidhya.com/blog/2025/08/google-gen-ai-python-sdk-guide/)  
9. Set up a project and a development environment | Vertex AI \- Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/vertex-ai/docs/start/cloud-environment](https://docs.cloud.google.com/vertex-ai/docs/start/cloud-environment)  
10. Enable Vertex AI APIs | Google Distributed Cloud air-gapped, accessed January 21, 2026, [https://docs.cloud.google.com/distributed-cloud/hosted/docs/latest/gdch/application/ao-user/vertex-ai-enable-pre-trained-apis](https://docs.cloud.google.com/distributed-cloud/hosted/docs/latest/gdch/application/ao-user/vertex-ai-enable-pre-trained-apis)  
11. Method: users.messages.attachments.get | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments/get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments/get)  
12. Authenticating Vertex AI Gemini API Calls in Python using Service Accounts (Without gcloud CLI) | by Lilian Li | Medium, accessed January 21, 2026, [https://medium.com/@lilianli1922/authenticating-vertex-ai-gemini-api-calls-in-python-using-service-accounts-without-gcloud-cli-e17203995ff1](https://medium.com/@lilianli1922/authenticating-vertex-ai-gemini-api-calls-in-python-using-service-accounts-without-gcloud-cli-e17203995ff1)  
13. Using OAuth 2.0 to Access Google APIs | Authorization, accessed January 21, 2026, [https://developers.google.com/identity/protocols/oauth2](https://developers.google.com/identity/protocols/oauth2)  
14. Authenticate | Generative AI on Vertex AI \- Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/vertex-ai/generative-ai/docs/migrate/openai/auth-and-credentials](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/migrate/openai/auth-and-credentials)  
15. Vertex AI access control with IAM | Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/vertex-ai/docs/general/access-control](https://docs.cloud.google.com/vertex-ai/docs/general/access-control)  
16. Submodules \- Google Gen AI SDK documentation \- googleapis.github.io, accessed January 21, 2026, [https://googleapis.github.io/python-genai/genai.html](https://googleapis.github.io/python-genai/genai.html)  
17. Retrieve Gmail attachment in Python using Gmail API in Python3.7 \- Stack Overflow, accessed January 21, 2026, [https://stackoverflow.com/questions/61687645/retrieve-gmail-attachment-in-python-using-gmail-api-in-python3-7](https://stackoverflow.com/questions/61687645/retrieve-gmail-attachment-in-python-using-gmail-api-in-python3-7)  
18. How to download Gmail attachments using Python 3.7 and the Gmail API?, accessed January 21, 2026, [https://community.latenode.com/t/how-to-download-gmail-attachments-using-python-3-7-and-the-gmail-api/10550](https://community.latenode.com/t/how-to-download-gmail-attachments-using-python-3-7-and-the-gmail-api/10550)  
19. Python Gmail API script not saving attachments — CSV shows filename but files are never downloaded \- Reddit, accessed January 21, 2026, [https://www.reddit.com/r/learnpython/comments/1ozog9f/python\_gmail\_api\_script\_not\_saving\_attachments/](https://www.reddit.com/r/learnpython/comments/1ozog9f/python_gmail_api_script_not_saving_attachments/)  
20. How can I get the body of a gmail email with an attatchment gmail python API, accessed January 21, 2026, [https://stackoverflow.com/questions/65885152/how-can-i-get-the-body-of-a-gmail-email-with-an-attatchment-gmail-python-api](https://stackoverflow.com/questions/65885152/how-can-i-get-the-body-of-a-gmail-email-with-an-attatchment-gmail-python-api)  
21. File input methods | Gemini API \- Google AI for Developers, accessed January 21, 2026, [https://ai.google.dev/gemini-api/docs/file-input-methods](https://ai.google.dev/gemini-api/docs/file-input-methods)  
22. Image understanding | Gemini API | Google AI for Developers, accessed January 21, 2026, [https://ai.google.dev/gemini-api/docs/image-understanding](https://ai.google.dev/gemini-api/docs/image-understanding)  
23. Document understanding | Gemini API \- Google AI for Developers, accessed January 21, 2026, [https://ai.google.dev/gemini-api/docs/document-processing](https://ai.google.dev/gemini-api/docs/document-processing)  
24. gemini-samples/examples/gemini-structured-outputs.ipynb at main \- GitHub, accessed January 21, 2026, [https://github.com/philschmid/gemini-samples/blob/main/examples/gemini-structured-outputs.ipynb](https://github.com/philschmid/gemini-samples/blob/main/examples/gemini-structured-outputs.ipynb)  
25. Structured output for open models | Generative AI on Vertex AI, accessed January 21, 2026, [https://docs.cloud.google.com/vertex-ai/generative-ai/docs/maas/capabilities/structured-output](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/maas/capabilities/structured-output)  
26. Structured output | Generative AI on Vertex AI \- Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output)  
27. Schema validation rejects additionalProperties \- Gemini API now supports since November 2025 · Issue \#1815 · googleapis/python-genai · GitHub, accessed January 21, 2026, [https://github.com/googleapis/python-genai/issues/1815](https://github.com/googleapis/python-genai/issues/1815)  
28. Image generation API \- Vertex AI \- Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/imagen-api](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/imagen-api)  
29. python-genai/codegen\_instructions.md at main · googleapis/python-genai \- GitHub, accessed January 21, 2026, [https://github.com/googleapis/python-genai/blob/main/codegen\_instructions.md](https://github.com/googleapis/python-genai/blob/main/codegen_instructions.md)
