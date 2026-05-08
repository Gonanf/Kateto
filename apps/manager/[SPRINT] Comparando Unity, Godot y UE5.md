



# Feature Overview

## Description


This project aims to provide a comprehensive technical comparison of Unity, Godot, and Unreal Engine 5 to help developers make informed engine selection decisions. It will evaluate key metrics such as rendering capabilities, scripting languages, performance overhead, and learning curve across different project scales. The final output will include benchmark data and suitability recommendations for various use cases.
## Values

- [ ] Reduces decision fatigue for indie developers and studios choosing a game engine
- [ ] Provides objective performance benchmarks for specific hardware configurations
- [ ] Highlights unique strengths of each engine to match project requirements
- [ ] Serves as an educational resource for developers transitioning between engines

## Dependencies

- [ ] Access to Unity, Godot, and Unreal Engine 5 development environments
- [ ] Standardized test scenes or projects for consistent benchmarking
- [ ] Hardware specifications for target testing machines
- [ ] Knowledge of C#, GDScript, and C++ for implementation

# Team capacity

|Name|Type|
| :---: | :---: |
|Chaos|Human|
|Kateto|Agent|

# Product Backlog Items

## Establish Standardized Benchmarking Infrastructure


Set up the hardware environment and create identical 'Hello World' to complex scene test cases for Unity, Godot, and Unreal Engine 5. This epic covers the preparation of test machines, installation of engine versions, and creation of the baseline assets (models, textures, scripts) that will be used across all three engines to ensure fair comparison.

Score: 13/13

Priority: 1/5
|Given|When|Then|
| :---: | :---: | :---: |
|The testing hardware is configured|The test scenes are imported into Unity, Godot, and UE5|The visual output and scene structure must be identical across all three engines.|
|The benchmarking tools are installed|The test scenes are run|Then the system must log FPS, memory usage, and CPU/GPU load automatically.|


Requires coordination between Chaos and Kateto to ensure asset parity across engines. Hardware specs must be documented.
## As an indie developer, I want to compare the initial setup and learning curve of each engine


Evaluate and document the time required to set up a basic 3D project in Unity, Godot, and UE5. Include metrics on IDE responsiveness, documentation clarity, and the ease of creating a basic camera and character controller.

Score: 5/13

Priority: 2/5
|Given|When|Then|
| :---: | :---: | :---: |
|A new developer opens each engine|They create a new 3D project and add a basic character controller|Then the time taken and number of steps required must be recorded and compared.|
|The developer consults documentation|They attempt to implement a basic movement script|Then the clarity and availability of examples must be rated on a scale of 1-5.|


Focus on the 'Day 1' experience for a new developer.
## Implement and Profile Rendering Benchmarks for High-Density Scenes


Create a scene with 10,000 instances of a complex mesh with dynamic lighting in each engine. Profile the rendering performance using built-in profilers (Unity Profiler, Godot Visual Profiler, Unreal Insights) to gather frame times and draw call counts.

Score: 8/13

Priority: 1/5
|Given|When|Then|
| :---: | :---: | :---: |
|The high-density scene is loaded|The camera moves through the scene|Then the minimum, average, and maximum frame times must be recorded for each engine.|
|The profiling session ends|The data is exported|Then the draw call count and memory footprint must be documented.|


Ensure lighting settings are normalized (e.g., same shadow quality, same post-processing stack).
## As a studio lead, I want to compare scripting language productivity and performance


Compare the implementation of a complex game mechanic (e.g., a state machine for AI behavior) using C# (Unity), GDScript (Godot), and C++ (UE5). Evaluate code verbosity, execution speed, and memory overhead.

Score: 8/13

Priority: 2/5
|Given|When|Then|
| :---: | :---: | :---: |
|The AI state machine is implemented|1000 AI agents run simultaneously|Then the CPU usage and script execution time per frame must be measured.|
|A feature is added to the AI logic|The developer modifies the code|Then the time taken to compile/reload and the number of lines of code must be compared.|


Focus on both developer experience (DX) and runtime performance.
## Analyze Mobile vs. Desktop Performance Discrepancies


Run the standardized test scenes on a mid-range desktop PC and a mid-range mobile device (or mobile emulator). Analyze the performance drop-off in each engine to determine suitability for cross-platform development.

Score: 5/13

Priority: 3/5
|Given|When|Then|
| :---: | :---: | :---: |
|The test scene is built for mobile|It is deployed to the target device|Then the frame rate stability and battery consumption must be recorded.|
|The build is complete|The build size is checked|Then the final APK/IPA/EXE file size must be compared.|


Godot and Unity have strong mobile support; UE5 is heavier. This is a critical differentiator.
## As a technical artist, I want to compare asset pipeline integration


Evaluate how easily 3D assets exported from Blender can be imported and optimized in each engine. Measure the time to import, material conversion issues, and texture compression options.

Score: 5/13

Priority: 3/5
|Given|When|Then|
| :---: | :---: | :---: |
|A FBX model with custom shaders is exported|It is imported into each engine|Then any manual adjustments required to make it look correct must be logged.|
|Textures are imported|The engine compresses them|Then the resulting visual quality and file size must be evaluated.|


Focus on the friction points in the art workflow.
## Compile Final Comparative Report and Recommendations


Synthesize all benchmark data, user story results, and task outcomes into a comprehensive report. Create a decision matrix that helps developers choose the right engine based on project type (2D, 3D, Mobile, AAA, Indie).

Score: 3/13

Priority: 1/5
|Given|When|Then|
| :---: | :---: | :---: |
|All data is collected|The report is generated|Then it must include clear recommendations for at least 5 distinct use cases.|
|The report is reviewed|It is published|Then it must be accessible to the target audience of indie developers and studio leads.|


This is the final deliverable. Ensure all data is visually represented in charts/graphs.
# Phases

## 1. Establish Infrastructure and Evaluate Developer Experience


Description: In this initial sprint, the team focuses on laying the groundwork for the comparison. Chaos and Kateto will configure the standardized hardware environment and create the baseline 'Hello World' to complex scene test cases (PBI: Establish Standardized Benchmarking Infrastructure). Simultaneously, they will evaluate the 'Day 1' experience for indie developers by measuring setup time, IDE responsiveness, and documentation clarity across Unity, Godot, and UE5 (PBI: Compare initial setup and learning curve). This ensures that the testing environment is ready and the subjective developer experience metrics are captured early.

Duration: 2 Weeks
|Title|Description|Asignee|Effort|
| :---: | :---: | :---: | :---: |
|Configure Standardized Hardware Environment and Install Engines|Chaos will set up the test machine with the specified hardware specs, install Unity, Godot, and Unreal Engine 5, and configure the benchmarking tools for automatic logging of FPS, memory, and CPU/GPU load. This ensures the infrastructure is ready for fair comparison.|Chaos(Human)|12.0 Hours|
|Create and Validate Baseline 'Hello World' Test Scenes|Kateto (Agent) will generate the baseline assets (models, textures, scripts) and create identical 'Hello World' to complex scene test cases in all three engines. Chaos will verify that the visual output and scene structure are identical across Unity, Godot, and UE5 to ensure asset parity.|Chaos(Human)|16.0 Hours|
|Execute Initial Setup and Learning Curve Evaluation|Chaos will simulate the 'Day 1' experience for a new indie developer. This includes measuring the time to set up a basic 3D project, creating a basic camera and character controller, and rating documentation clarity on a scale of 1-5 for each engine.|Chaos(Human)|10.0 Hours|
|Automate Baseline Benchmark Data Collection|Kateto (Agent) will run the baseline test scenes created in the previous task and automatically log the system metrics (FPS, memory usage, CPU/GPU load) using the installed benchmarking tools. This data will serve as the control group for future comparisons.|Kateto(Agent)|8.0 Hours|
|Document IDE Responsiveness and Setup Metrics|Chaos will compile the results from the initial setup evaluation, documenting IDE responsiveness, step counts, and time metrics. This report will be formatted for the final sprint deliverable and shared with the team for review.|Chaos(Human)|6.0 Hours|
|Verify Hardware Configuration and Asset Parity|Chaos will perform a final audit of the hardware configuration and the baseline assets to ensure they meet the criteria defined in the 'Establish Standardized Benchmarking Infrastructure' PBI. Any discrepancies in visual output or scene structure must be corrected before the next sprint.|Chaos(Human)|5.0 Hours|


## 2. Execute Technical Benchmarks and Pipeline Analysis


Description: With the infrastructure established, the team will execute the core technical comparisons. This includes implementing and profiling rendering benchmarks for high-density scenes to gather frame times and draw call data (PBI: Implement and Profile Rendering Benchmarks). Concurrently, they will compare scripting language productivity by implementing a complex AI state machine in C#, GDScript, and C++, measuring both code verbosity and runtime performance (PBI: Compare scripting language productivity). Finally, the art workflow friction will be assessed by importing Blender assets and analyzing material conversion and texture compression issues (PBI: Compare asset pipeline integration).

Duration: 3 Weeks
|Title|Description|Asignee|Effort|
| :---: | :---: | :---: | :---: |
|Implement High-Density Rendering Benchmark Scene|Create the standardized test scene containing 10,000 instances of a complex mesh with dynamic lighting. Ensure lighting settings (shadow quality, post-processing) are normalized across Unity, Godot, and UE5 to guarantee fair comparison. Export the scene assets and project structures for profiling.|Chaos(Human)|12.0 Hours|
|Execute Rendering Benchmarks and Profile Performance|Run the high-density scene in all three engines using their respective built-in profilers (Unity Profiler, Godot Visual Profiler, Unreal Insights). Record minimum, average, and maximum frame times, draw call counts, and memory footprint. Export raw data for analysis.|Kateto(Agent)|10.0 Hours|
|Implement AI State Machine in C#, GDScript, and C++|Develop a complex AI behavior state machine in Unity (C#), Godot (GDScript), and UE5 (C++). The implementation must support 1000 simultaneous agents. Focus on clean architecture to measure code verbosity and execution speed effectively.|Chaos(Human)|16.0 Hours|
|Profile AI Scripting Performance and Verbosity|Run the AI state machine implementation with 1000 agents in each engine. Measure CPU usage, script execution time per frame, and compile/reload times. Document the number of lines of code and developer experience friction points for each language.|Kateto(Agent)|10.0 Hours|
|Setup Blender Asset Pipeline for Cross-Engine Import|Prepare a standard FBX model with custom shaders and textures from Blender. Define the import settings and material conversion workflows for Unity, Godot, and UE5. Identify potential friction points in the art workflow.|Chaos(Human)|8.0 Hours|
|Analyze Asset Import Friction and Texture Compression|Import the Blender assets into all three engines. Log any manual adjustments required for visual parity. Evaluate texture compression options, resulting file sizes, and visual quality degradation. Compile findings on pipeline efficiency.|Kateto(Agent)|12.0 Hours|


## 3. Analyze Cross-Platform Performance and Finalize Report


Description: The final sprint focuses on cross-platform viability and synthesis. The team will run the standardized test scenes on both mid-range desktop and mobile devices to analyze performance discrepancies, frame rate stability, and build sizes (PBI: Analyze Mobile vs. Desktop Performance Discrepancies). All collected data from previous sprints will be synthesized into a comprehensive comparative report, including a decision matrix for different project types, ensuring clear recommendations for indie developers and studio leads (PBI: Compile Final Comparative Report and Recommendations).

Duration: 2 Weeks
|Title|Description|Asignee|Effort|
| :---: | :---: | :---: | :---: |
|Execute Mobile Benchmarking on Mid-Range Devices|Deploy the standardized test scenes (established in previous sprints) to a mid-range mobile device (or high-fidelity emulator). Run the high-density rendering scene and the AI state machine simulation. Record frame rate stability, battery consumption, and final build sizes (APK/IPA) for Unity, Godot, and UE5. Compare these metrics against the desktop results to identify performance discrepancies.|Kateto(Agent)|24.0 Hours|
|Analyze Mobile vs. Desktop Performance Data|Process the raw data collected from the mobile benchmarks. Calculate the performance drop-off percentages for CPU, GPU, and memory usage between desktop and mobile builds. Evaluate the trade-offs in build size and battery life. Document findings specifically regarding cross-platform viability, highlighting where Godot and Unity outperform UE5 on mobile constraints.|Chaos(Human)|16.0 Hours|
|Synthesize Cross-Platform Findings into Decision Matrix|Integrate the mobile performance analysis with previous sprint data (rendering, scripting, asset pipeline). Create a comprehensive decision matrix that categorizes engine suitability for specific use cases (e.g., Mobile Indie, Desktop AAA, 2D Mobile, etc.). Ensure the matrix clearly visualizes the trade-offs between performance overhead and development speed for each engine.|Chaos(Human)|20.0 Hours|
|Generate Final Comparative Report with Visualizations|Compile all benchmark data, user story results, and the new mobile analysis into the final comparative report. Generate clear charts and graphs to represent FPS, memory usage, and build sizes. Write the executive summary and detailed recommendations for indie developers and studio leads, ensuring the report is accessible and actionable.|Chaos(Human)|25.0 Hours|
|Automate Report Data Formatting and Publication|Assist in the final formatting of the report by automating the insertion of benchmark data into the template. Ensure all charts are correctly linked to the source data. Perform a final quality check to ensure the report meets the criteria of being accessible to the target audience and includes recommendations for at least 5 distinct use cases.|Kateto(Agent)|12.0 Hours|


# Definition of Done

## Code Quality

- [ ] All source code (C# for Unity, GDScript for Godot, C++ for UE5) has passed peer review by at least one other team member.
- [ ] Code adheres to the official style guides for each respective engine/language (e.g., Unity C# Style Guide, Google C++ Style Guide for UE5).
- [ ] Static analysis tools (e.g., SonarQube for C#, Clang-Tidy for C++, LSP servers for GDScript) report zero critical or high-severity issues.
- [ ] No unused variables, methods, or assets remain in the codebase after profiling and cleanup.
- [ ] All engine-specific scripts are modularized and avoid tight coupling to ensure maintainability and ease of comparison.

## Testing

- [ ] Automated benchmarks for 'Hello World' and high-density scenes have been executed and logged for all three engines.
- [ ] Integration tests confirm that the standardized test scenes produce visually identical outputs across Unity, Godot, and UE5 (verified via screenshot diffing or pixel-perfect comparison tools).
- [ ] Unit tests for the AI state machine implementation verify logic correctness and edge cases for all three scripting languages.
- [ ] Test coverage thresholds are met for core logic modules (e.g., >80% coverage for the AI behavior tree logic).
- [ ] Cross-platform builds (Desktop vs. Mobile/Emulator) have been tested, and performance discrepancies are documented and acceptable within defined tolerances.

## Documentation

- [ ] A comprehensive README.md is updated with instructions on how to reproduce the benchmarks, including hardware specs and engine versions used.
- [ ] Inline comments explain complex optimization techniques and engine-specific quirks identified during the rendering and scripting comparisons.
- [ ] API documentation for any custom helper scripts or benchmarking tools is generated and accessible.
- [ ] The 'Learning Curve' evaluation includes documented steps, screenshots of IDE setup, and ratings for documentation clarity for each engine.
- [ ] The final Comparative Report includes a decision matrix with clear recommendations for at least 5 distinct use cases (2D, 3D, Mobile, AAA, Indie).

## Deployment

- [ ] All project builds (Unity, Godot, UE5) compile successfully without errors or warnings in their respective release configurations.
- [ ] Deployment scripts or build pipelines are documented, allowing for automated reproduction of the final deliverables.
- [ ] Environment configurations for the testing hardware are archived and version-controlled to ensure reproducibility.
- [ ] Final binaries (EXE, APK, IPA) are generated and stored in a designated artifact repository with size metrics recorded.
- [ ] The final report is published in a format accessible to the target audience (e.g., PDF, web page) and includes all raw benchmark data as appendices.

## Performance

- [ ] Rendering benchmarks include recorded minimum, average, and maximum frame times for high-density scenes (10,000 instances).
- [ ] Draw call counts and memory footprints are documented and compared across all three engines for standardized scenes.
- [ ] CPU usage and script execution time per frame are measured for the AI state machine with 1,000 simultaneous agents.
- [ ] Mobile performance metrics include frame rate stability and battery consumption data, highlighting any significant drop-offs compared to desktop.
- [ ] Build size metrics (APK/IPA/EXE) are recorded and compared to assess overhead and optimization levels.
