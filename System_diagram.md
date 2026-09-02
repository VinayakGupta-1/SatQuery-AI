# SatQuery AI — System Diagram
                          ┌──────────────────────┐
                          │         USER         │
                          │   Natural-Language   │
                          │   Query + Image(s)   │
                          └──────────┬───────────┘
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │      REACT + TYPESCRIPT      │
                      │           FRONTEND           │
                      │                              │
                      │  • Query Input               │
                      │  • Image Upload              │
                      │  • Results Visualization     │
                      └──────────────┬───────────────┘
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │           FASTAPI            │
                      │         BACKEND API          │
                      │                              │
                      │  • Request Handling          │
                      │  • File Handling             │
                      │  • Response Management       │
                      └──────────────┬───────────────┘
                                     │
                                     ▼
              ┌─────────────────────────────────────────────┐
              │             AGENTIC CONTROLLER              │
              │                                             │
              │   • Query Understanding                     │
              │   • Task Classification                     │
              │   • Workflow Planning                       │
              │   • Input Requirement Generation            │
              │   • Tool / Model Selection                  │
              │   • Parameter Configuration                 │
              │   • Execution Orchestration                 │
              └───────┬─────────────────────────────┬───────┘
                      │                              │
                      ▼                              ▼
          ┌────────────────────────┐    ┌────────────────────────┐
          │     DETERMINISTIC      │    │   CONTROLLED TOOL &    │
          │    INPUT VALIDATOR     │    │     MODEL REGISTRY     │
          │                        │    │                        │
          │ • Format Validation    │    │ • Registered Tools     │
          │ • Image Count          │    │ • Model Definitions    │
          │ • Modality             │    │ • Input Schema         │
          │ • Metadata             │    │ • Parameter Schema     │
          │ • CRS Compatibility    │    │ • Output Schema        │
          │ • Temporal Checks      │    │ • Version Metadata     │
          │ • Input Compatibility  │    │                        │
          └───────────┬────────────┘    └───────────┬────────────┘
                      │                              │
                      └──────────────┬───────────────┘
                                     ▼
                 ┌──────────────────────────────────────┐
                 │     REMOTE-SENSING TOOL / MODEL      │
                 │                LAYER                 │
                 │                                      │
                 │  ┌──────────┐  ┌──────────────────┐  │
                 │  │   NDVI   │  │   Segmentation   │  │
                 │  └──────────┘  └──────────────────┘  │
                 │  ┌──────────┐  ┌──────────────────┐  │
                 │  │   NDWI   │  │ Object Detection │  │
                 │  └──────────┘  └──────────────────┘  │
                 │  ┌──────────┐  ┌──────────────────┐  │
                 │  │   NDBI   │  │ Change Detection │  │
                 │  └──────────┘  └──────────────────┘  │
                 │  ┌──────────┐  ┌──────────────────┐  │
                 │  │   VQA    │  │  LULC Classifier │  │
                 │  └──────────┘  └──────────────────┘  │
                 └───────────────────┬──────────────────┘
                                     │
                                     ▼
                 ┌──────────────────────────────────────┐
                 │          RESULT INTEGRATION          │
                 │                                      │
                 │  • Process Model Output              │
                 │  • Combine Multi-Step Results        │
                 │  • Generate Explanation              │
                 │  • Prepare Visualization Payload     │
                 └───────────────────┬──────────────────┘
                                     │
                                     ▼
                 ┌──────────────────────────────────────┐
                 │           FRONTEND OUTPUT            │
                 │                                      │
                 │  • Maps & Overlays                   │
                 │  • Statistics                        │
                 │  • Detection / Segmentation Results  │
                 │  • Natural-Language Explanation      │
                 └──────────────────────────────────────┘
