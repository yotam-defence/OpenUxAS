# Ada → C++ gap analysis

Classification of every Ada unit under `src/ada/src` against the C++ code in `src/cpp`. It feeds milestones 2-6.

Categories: **covered** = covered by C++, **port** = needs port, **drop** = Ada-only, drop at removal.

Initial classification from unit names and the C++ file layout, to be confirmed during each consuming milestone. It is not a line-by-line behavioral comparison.

| Ada area | Ada units | C++ counterpart | Class | Milestone |
|---|---|---|---|---|
| utils | `bounded_dynamic_arrays`, `bounded_stack`, `bounded_dynamic_strings`, `dynamic_strings` | `std::vector` / `std::string` | drop | 7 |
| utils | `string_utils`, `int64_parsing` | `Utilities/UxAS_StringUtil.h` | covered (verify parsing edge cases) | 2 |
| utils | `unit_conversion_utilities` | `Utilities/UnitConversions` | covered | 2 |
| common | `uxas-common-configuration_manager` | `Utilities/UxAS_ConfigurationManager` | covered | 2 |
| common | `uxas-common-sentinel_serial_buffers` | `Utilities/UxAS_SentinelSerialBuffer` | covered | 2 |
| common | `uxas-common-string_constant*` | constants inline in C++ sources | covered | 2 |
| comms | `uxas-comms-data*` (addressed, attributed, lmcp_messages) | `Communications/AddressedMessage.h`, `AddressedAttributedMessage`, `MessageAttributes.h`, `LmcpMessage.h` | covered | 2 |
| comms | `uxas-comms-lmcp_object_message_{receiver,sender}_pipes` | `Communications/LmcpObjectMessage{Receiver,Sender}Pipe` | covered | 2 |
| comms | `uxas-comms-transport-*` (zeromq fabric, receivers, senders, socket configurations, network_name) | `Communications/LmcpObjectNetwork*Bridge`, `ZeroMqFabric` | covered | 2 |
| comms | `uxas-comms-lmcp_net_client` | `Communications/LmcpObjectNetworkClientBase` | covered | 2 |
| main | `uxas_ada.adb` | `UxAS_Main.cpp` | covered (`-help`/`--version` added in milestone 1) | 2 |
| main | `ctrl_c_handler*` | signal handling in `UxAS_Main.cpp` | covered | 2 |
| services/arv | `automation_request_validator*` and its interfacing unit | `Services/AutomationRequestValidatorService` | covered; reconcile behavior | 3 |
| services/route_aggregator | `route_aggregator*` and its interfacing unit | `Services/RouteAggregatorService` | covered; reconcile behavior | 4 |
| services/atbb | `assignment_tree_branch_bound*`, `algebra` | `Services/AssignmentTreeBranchBound{Service,Base}` | covered; reconcile behavior | 5 |
| services/waypoint_manager | `waypoint_plan_manager*` and its interfacing unit | `Services/WaypointPlanManagerService` | covered; reconcile behavior | 6 |
| services | `uxas-comms-lmcp_net_client-service` | `Services/ServiceBase` | covered | 2 |
| services/template | `template.txt`, `instantiate`, `README.md` | `Services/00_NewService.py`, `00_ServiceTemplate.*` | drop | 7 |
| services/spark | `*-spark_boundary`, `common`, `common_formal_containers`, `lmcp_message_conversions`, `lmcp_messages` (located at `src/ada/src/services/spark`, not a top-level `spark` dir) | none (SPARK proof boundary only) | drop | 7 |
| tests | `src/ada/src/tests` | `tests/cpp/unit`, `tests/cpp/difftest` | port as needed | 2-6 |
