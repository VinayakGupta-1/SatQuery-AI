# SatQuery AI — System Architecture

> Companion document: [System_diagram.md](System_diagram.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architectural Goals](#2-architectural-goals)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Frontend Layer](#4-frontend-layer)
5. [Backend API Layer](#5-backend-api-layer)
6. [Agentic Controller](#6-agentic-controller)
7. [Deterministic Input Validator](#7-deterministic-input-validator)
8. [Controlled Tool and Model Registry](#8-controlled-tool-and-model-registry)
9. [Remote-Sensing Model and Tool Layer](#9-remote-sensing-model-and-tool-layer)
10. [Result Integration Layer](#10-result-integration-layer)
11. [Example End-to-End Workflow](#11-example-end-to-end-workflow)
12. [Error Handling](#12-error-handling)
13. [Security and Reliability Principles](#13-security-and-reliability-principles)
14. [Backend Project Structure](#14-backend-project-structure)
15. [Testing Strategy](#15-testing-strategy)
16. [Design Philosophy](#16-design-philosophy)
17. [Architectural Summary](#17-architectural-summary)

---

## 1. Overview

**SatQuery AI** is an agentic, AI-powered satellite imagery analysis platform that lets
users perform remote-sensing tasks through natural-language queries.

Instead of requiring users to understand satellite data formats, spectral bands,
remote-sensing algorithms, or individual machine-learning models, SatQuery interprets the
user's intent and converts it into an executable analysis workflow.

The system follows this pipeline:

```text
User
  │
  ▼
React + TypeScript Frontend
  │
  ▼
FastAPI Backend
  │
  ▼
Agentic Controller
  │   ├── Query Understanding
  │   ├── Task Classification
  │   ├── Planning
  │   ├── Input Requirement Generation
  │   ├── Tool / Model Selection
  │   ├── Parameter Configuration
  │   └── Execution Orchestration
  ▼
Deterministic Input Validator
  │   ├── File / Format Validation
  │   ├── Image Count Validation
  │   ├── Modality Validation
  │   ├── Metadata Validation
  │   ├── CRS Validation
  │   ├── Temporal Compatibility
  │   └── Input Compatibility
  ▼
Controlled Tool & Model Registry
  │
  ▼
Remote-Sensing Model / Tool Layer
  │   ├── VQA
  │   ├── Segmentation
  │   ├── Object Detection
  │   ├── Change Detection
  │   ├── Spectral Index Computation
  │   └── Other Remote-Sensing Operations
  ▼
Result Integration
  │
  ▼
Response / Visualization
  │
  ▼
Frontend
```

---

## 2. Architectural Goals

The architecture is designed around four principles.

### 2.1 Natural-Language Interaction

Users describe an analysis task without manually selecting models or configuring complex
remote-sensing pipelines.

> **Example query:** "Calculate vegetation health for this satellite image."

The system determines that this corresponds to an appropriate vegetation-index workflow,
such as NDVI, provided the required input bands are available.

### 2.2 Agentic Decision Making

The **Agentic Controller** reasons over the user's request and determines:

* What task the user wants to perform
* What inputs are required
* Which tool or model is appropriate
* What parameters are required
* What execution steps are necessary
* How results should be combined and returned

The controller does **not** directly execute arbitrary code or arbitrary tools. It
operates over a **controlled registry of approved tools and models**.

### 2.3 Deterministic Validation

LLM-based reasoning is not trusted for strict input validation, so validation is
implemented as a separate deterministic subsystem. The validator verifies:

| Requirement | Checked |
|---|---|
| File format | Supported extension and readable container |
| Number of images | Matches the operation's arity |
| Required bands | Present in the supplied raster |
| Image modality | Optical / SAR / multispectral / hyperspectral |
| Metadata | Acquisition, sensor, band, resolution info |
| Coordinate reference system | Present and mutually compatible |
| Temporal compatibility | Satisfies multi-temporal requirements |
| Spatial compatibility | Overlapping extent and comparable grid |
| Input compatibility | Inputs match the selected operation |

This separates probabilistic reasoning from deterministic correctness checks.

### 2.4 Controlled Execution

The agent cannot freely call arbitrary Python functions, APIs, or external services.
Every executable capability is exposed through a predefined tool/model registry, which
provides:

* Predictable execution
* Validation of parameters
* Safer tool invocation
* Easier testing
* Easier replacement of models
* Reproducible workflows

---

## 3. High-Level Architecture

SatQuery AI is divided into the following major layers:

```text
┌───────────────────────────────────────────────┐
│                Presentation Layer             │
│              React + TypeScript GUI           │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│                    API Layer                  │
│                     FastAPI                   │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│               Agentic Controller              │
│                                               │
│  Query Understanding                          │
│  Task Classification                          │
│  Planning                                     │
│  Input Requirements                           │
│  Tool / Model Selection                       │
│  Parameter Configuration                      │
│  Execution Orchestration                      │
└──────────┬──────────────────────────┬─────────┘
           │                          │
           ▼                          ▼
┌────────────────────┐    ┌────────────────────┐
│ Deterministic      │    │ Tool / Model       │
│ Input Validator    │    │ Registry           │
└─────────┬──────────┘    └─────────┬──────────┘
          │                         │
          └────────────┬────────────┘
                       ▼
        ┌──────────────────────────────┐
        │  Remote-Sensing Models &      │
        │  Tools                        │
        └───────────────┬──────────────┘
                        │
                        ▼
        ┌──────────────────────────────┐
        │  Result Integration &         │
        │  Response Generation          │
        └───────────────┬──────────────┘
                        │
                        ▼
        ┌──────────────────────────────┐
        │  Frontend Visualization       │
        └──────────────────────────────┘
```

---

## 4. Frontend Layer

### 4.1 Technology

* React
* TypeScript
* Vite
* HTML / CSS
* REST API communication

### 4.2 Responsibilities

The frontend provides the user-facing interface and is responsible for:

1. Accepting natural-language queries
2. Uploading satellite imagery
3. Displaying input requirements
4. Showing validation errors
5. Displaying execution status
6. Presenting analysis results
7. Visualizing outputs where applicable

The frontend does **not** contain core reasoning logic. Decision-making and validation
remain in the backend.

---

## 5. Backend API Layer

### 5.1 Technology

**FastAPI + Python.** The backend is the interface between the frontend and the SatQuery
processing system.

### 5.2 Responsibilities

* Query submission
* Image / file uploads
* Request validation
* Agent invocation
* Workflow execution
* Result delivery
* Error handling

### 5.3 Example Request

```http
POST /analyze
Content-Type: application/json

{
    "query": "Find areas affected by flooding",
    "inputs": [...]
}
```

The backend passes the request to the Agentic Controller.

---

## 6. Agentic Controller

The **Agentic Controller** is the central intelligence and orchestration layer of
SatQuery. Its purpose is not to perform every remote-sensing operation itself, but to
determine **what needs to be done and how it should be executed**.

### 6.1 Query Understanding

The controller interprets the natural-language request.

**Input:**

```text
"Compare these two satellite images and identify areas
where land cover has changed."
```

**Extracted intent:**

```text
Task:            Change Detection
Inputs:          Image A, Image B
Expected Output: Change map / detected regions
```

### 6.2 Task Classification

The query is mapped to a supported remote-sensing task:

* Visual Question Answering
* Image Segmentation
* Object Detection
* Change Detection
* Land-Use / Land-Cover Classification
* NDVI computation
* NDWI computation
* NDBI computation
* Scene classification
* Other registered remote-sensing operations

### 6.3 Planning

The controller determines the steps required to execute the requested task:

```text
User Query
    │
    ▼
Identify task
    │
    ▼
Determine required inputs
    │
    ▼
Validate inputs
    │
    ▼
Select appropriate tool / model
    │
    ▼
Configure parameters
    │
    ▼
Execute
    │
    ▼
Integrate results
    │
    ▼
Return response
```

### 6.4 Input Requirement Generation

Before execution, the controller determines what information is required. For example:

```text
Required Inputs:
  - Satellite image
  - Specific spectral bands
  - Spatial reference information
  - Acquisition metadata
```

The user receives a clear explanation of missing requirements rather than an obscure
model error.

### 6.5 Tool / Model Selection

The controller selects an appropriate capability from the controlled registry.

**Example A**

```text
Task:               Vegetation analysis
Selected operation: NDVI
Required bands:     Red, NIR
```

**Example B**

```text
Task:               Identify buildings
Selected model:     Registered object-detection model
Required input:     Compatible satellite image
```

### 6.6 Parameter Configuration

The controller determines the parameters required by the selected tool:

* Confidence threshold
* Image resolution
* Classification settings
* Band selection
* Temporal comparison parameters
* Segmentation settings

Parameters are validated before execution.

### 6.7 Execution Orchestration

The controller coordinates execution of the selected tools and models. A workflow can
contain multiple steps:

```text
Query
  │
  ▼
Input validation
  │
  ▼
Preprocessing
  │
  ▼
Model execution
  │
  ▼
Post-processing
  │
  ▼
Result integration
```

---

## 7. Deterministic Input Validator

The Input Validator is intentionally separated from the LLM / agent. Its purpose is to
provide **strict, deterministic verification** of input requirements. It does not decide
what the user means:

```text
Agent      → "What is required?"
Validator  → "Are the supplied inputs actually valid?"
```

### 7.1 File Validation

* File existence
* File type
* Supported formats
* File integrity

### 7.2 Image Count Validation

Some operations require a specific number of images:

```text
Single-image task  →  1 image
Change detection   →  2 compatible images
```

### 7.3 Modality Validation

The validator verifies that the supplied data matches the expected modality:

```text
Optical · SAR · Multispectral · Hyperspectral
```

### 7.4 Metadata Validation

* Acquisition date
* Sensor information
* Band information
* Spatial resolution
* Geographic information

### 7.5 CRS Validation

Geospatial operations may require compatible coordinate reference systems. The validator
checks CRS compatibility before execution.

### 7.6 Temporal Compatibility

For multi-temporal analysis, images must satisfy temporal requirements. For example:

```text
Image A  →  January 2025
Image B  →  January 2026
```

may be suitable for a year-over-year comparison, depending on the requested analysis.

### 7.7 Input Compatibility

The validator ensures that the supplied inputs are compatible with the selected
operation. If requirements are not satisfied, **execution stops before the model is
called**.

---

## 8. Controlled Tool and Model Registry

The registry is a controlled catalogue of the capabilities available to the Agentic
Controller:

```text
Tool Registry
│
├── NDVI Calculator
├── NDWI Calculator
├── NDBI Calculator
├── Image Segmentation
├── Object Detection
├── Change Detection
├── Land-Cover Classification
└── Visual Question Answering
```

Each registry entry defines:

| Field | Purpose |
|---|---|
| `tool_id` | Stable unique identifier |
| `name` | Human-readable name |
| `description` | Used by the controller during selection |
| `task_type` | Remote-sensing task category |
| `input_requirements` | What the validator must confirm |
| `parameter_schema` | Accepted parameters and their types |
| `output_schema` | Shape of the returned result |
| `execution_handler` | Callable that performs the work |
| `version` | Enables reproducibility and model swaps |

This prevents the agent from inventing nonexistent tools or calling arbitrary functions.

---

## 9. Remote-Sensing Model and Tool Layer

This layer contains the actual analytical capabilities. The architecture deliberately
separates the **agent's decision-making** from the **specialist execution layer**.

### 9.1 Spectral Index Analysis

* NDVI
* NDWI
* NDBI

### 9.2 Computer Vision

* Object Detection
* Image Segmentation
* Scene Classification

### 9.3 Remote-Sensing Analysis

* Change Detection
* Land-Use / Land-Cover Classification
* Multispectral analysis
* SAR analysis

### 9.4 Vision-Language Tasks

* Satellite-image Visual Question Answering

Each capability exposes a predictable input/output interface to the controller.

---

## 10. Result Integration Layer

After tool/model execution, results pass to the Result Integration layer, which is
responsible for:

* Combining outputs from multiple steps
* Converting raw model outputs into structured results
* Generating human-readable explanations
* Preparing visualization data
* Returning confidence / metadata where available

```text
Model Output
     │
     ▼
Post-processing
     │
     ▼
Structured Result
     │
     ▼
Human-readable Explanation
     │
     ▼
Frontend Visualization
```

---

## 11. Example End-to-End Workflow

> **Query:** "Compare these two satellite images and show me where vegetation has
> decreased."

### Step 1 — User Input

```text
Query:
  Compare these two satellite images and show me where
  vegetation has decreased.

Inputs:
  Image A
  Image B
```

### Step 2 — Query Understanding

The Agentic Controller identifies:

```text
Task: Temporal vegetation-change analysis
```

### Step 3 — Planning

The controller determines the required workflow:

```text
1. Validate both images
2. Verify required spectral information
3. Compute vegetation-related measurements
4. Compare the measurements
5. Generate a change map
```

### Step 4 — Validation

The deterministic validator checks:

```text
✓ Two images supplied
✓ Compatible modality
✓ Required bands available
✓ Metadata available
✓ Spatial compatibility
✓ Temporal information available
```

If validation fails:

```text
Execution stopped
       │
       ▼
User receives actionable error
```

### Step 5 — Tool Selection

The controller selects registered tools for:

```text
Vegetation index calculation  +  Temporal comparison
```

### Step 6 — Execution

The selected tools process the imagery.

### Step 7 — Result Integration

The system generates:

```text
Vegetation change map  +  Summary statistics  +  Human-readable explanation
```

### Step 8 — Frontend

The frontend displays the result to the user.

---

## 12. Error Handling

SatQuery fails safely and provides meaningful errors, grouped into categories:

```text
Input Error
    ├── Invalid file
    ├── Missing input
    ├── Wrong modality
    ├── Missing metadata
    └── Incompatible images

Planning Error
    └── Unsupported task

Tool Error
    ├── Invalid parameters
    └── Execution failure

Model Error
    └── Inference failure

System Error
    └── Unexpected backend failure
```

The system never exposes raw internal exceptions to the user.

---

## 13. Security and Reliability Principles

### 13.1 Controlled Tool Execution

The agent can only select tools exposed through the registry.

### 13.2 Deterministic Validation

Critical input constraints are enforced programmatically rather than relying solely on
LLM reasoning.

### 13.3 Schema Validation

Pydantic schemas validate structured requests, responses, tool parameters, and system
objects.

### 13.4 Separation of Concerns

The system keeps three responsibilities distinct:

```text
Reasoning  ≠  Validation  ≠  Execution
```

This makes the architecture easier to test and maintain.

---

## 14. Backend Project Structure

The backend is organized around clear architectural boundaries:

```text
backend/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── inputs.py
│   │   ├── task.py
│   │   ├── errors.py
│   │   └── ...
│   │
│   ├── validator/
│   │   └── ...
│   │
│   ├── agent/
│   │   └── ...
│   │
│   ├── registry/
│   │   └── ...
│   │
│   ├── tools/
│   │   └── ...
│   │
│   ├── models/
│   │   └── ...
│   │
│   ├── services/
│   │   └── ...
│   │
│   └── api/
│       └── ...
│
└── tests/
    ├── test_schemas.py
    ├── test_validator.py
    ├── test_agent.py
    └── ...
```

The exact structure may evolve as additional capabilities are implemented.

---

## 15. Testing Strategy

Testing is performed at three levels.

### 15.1 Unit Testing

Individual components are tested independently:

```text
Schema validation
Input validation
Tool parameter validation
Task classification
```

### 15.2 Integration Testing

Multiple components are tested together:

```text
API  →  Agent  →  Validator  →  Registry
```

### 15.3 End-to-End Testing

The complete workflow is exercised:

```text
User Query  →  API  →  Agentic Controller  →  Validation
            →  Tool Selection  →  Execution  →  Result
```

The goal is to ensure the system behaves correctly as a complete application, not merely
that isolated unit tests pass.

---

## 16. Design Philosophy

SatQuery AI is built on a **hybrid architecture**.

**LLMs are used where flexibility and semantic reasoning are valuable:**

```text
Natural Language  →  Intent Understanding  →  Task Planning  →  Tool Selection
```

**Deterministic software is used where correctness is critical:**

```text
Input Validation  →  Schema Validation  →  Parameter Validation  →  Tool Execution
```

This combination provides the flexibility of an agentic interface while maintaining
predictable, testable execution.

---

## 17. Architectural Summary

```text
                       USER
                       │
                       ▼
      ┌──────────────────────────────────┐
      │    React + TypeScript Frontend   │
      └────────────────┬─────────────────┘
                       │
                       ▼
      ┌──────────────────────────────────┐
      │       FastAPI Backend API        │
      └────────────────┬─────────────────┘
                       │
                       ▼
      ┌──────────────────────────────────┐
      │        AGENTIC CONTROLLER        │
      │                                  │
      │   Understand → Classify → Plan   │
      │ Select → Configure → Orchestrate │
      └──────┬───────────────────┬───────┘
             │                   │
             ▼                   ▼
     ┌───────────────┐   ┌───────────────┐
     │ Deterministic │   │ Tool / Model  │
     │   Validator   │   │   Registry    │
     └───────┬───────┘   └───────┬───────┘
             │                   │
             └─────────┬─────────┘
                       ▼
      ┌──────────────────────────────────┐
      │  Remote-Sensing Tools & Models   │
      └────────────────┬─────────────────┘
                       │
                       ▼
      ┌──────────────────────────────────┐
      │        Result Integration        │
      └────────────────┬─────────────────┘
                       │
                       ▼
      ┌──────────────────────────────────┐
      │  Visualization & User Response   │
      └──────────────────────────────────┘
```

The key architectural idea is that **SatQuery AI is not simply a collection of
satellite-image models**. It is an agentic orchestration layer that translates
natural-language requests into validated remote-sensing workflows, while keeping
execution constrained to known, testable capabilities.
