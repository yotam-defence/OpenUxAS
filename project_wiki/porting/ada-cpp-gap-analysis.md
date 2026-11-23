# Ada → C++ gap analysis

Classifies every Ada unit under `src/ada/src` (plus `src/ada/proof`) against the C++ tree in `src/cpp`.

**Classifications** (exact strings, so later milestones can grep them):
`covered by C++` · `needs port` · `drop`

**Method.** Units were enumerated with `find src/ada/src -name '*.ad[sb]'` and matched to C++ counterparts by name and role. Classifications are a first-pass triage from structure and naming. Each owning milestone must confirm behaviour with a scenario in `tests/cpp/differential` before deleting the Ada unit. Behavioural differences found there belong in the Notes column of this page.

Milestones: M2 = Ada utilities/common/comms/main gap port, M3 = Automation Request Validator, M4 = Route Aggregator, M5 = Assignment Tree Branch and Bound, M6 = Waypoint Plan Manager, M7 = Ada removal.

## utils

| Ada unit | C++ counterpart | Classification | Milestone | Notes |
|---|---|---|---|---|
| `utils/bounded_dynamic_arrays` | `std::vector` | drop | M7 | Ada bounded-container helper, SPARK-driven. |
| `utils/bounded_dynamic_strings` | `std::string` | drop | M7 | As above. |
| `utils/bounded_stack` | `std::stack` / `std::vector` | drop | M7 | As above. |
| `utils/dynamic_strings` | `std::string` | drop | M7 | As above. |
| `utils/int64_parsing` | `std::stoll`, `Includes/UxAS_StringUtil.h` | covered by C++ | M2 | Confirm edge cases (overflow, whitespace). |
| `utils/string_utils` | `Includes/UxAS_StringUtil.h` | covered by C++ | M2 | Confirm function-by-function. |
| `utils/unit_conversion_utilities` | `Utilities/UnitConversions.*` | covered by C++ | M2 | Check rounding vs Ada. |

## common

| Ada unit | C++ counterpart | Classification | Milestone | Notes |
|---|---|---|---|---|
| `common/uxas-common` | n/a (namespace root) | drop | M7 | |
| `common/uxas-common-configuration_manager` | `Utilities/UxAS_ConfigurationManager.*` | covered by C++ | M2 | Compare XML config parsing. |
| `common/uxas-common-sentinel_serial_buffers` | `Includes/UxAS_SentinelSerialBuffer.*` | covered by C++ | M2 | |
| `common/uxas-common-string_constant` | `Includes/UxAS_*` string constants | needs port | M2 | Verify every constant has a C++ equivalent. |
| `common/uxas-common-string_constant-content_type` | `Includes/UxAS_*` | needs port | M2 | As above. |
| `common/uxas-common-string_constant-lmcp_network_socket_address` | `Includes/UxAS_*` | needs port | M2 | As above. |
| `common/uxas-common-string_constant-message_group` | `Includes/UxAS_*` | needs port | M2 | As above. |

## comms

| Ada unit | C++ counterpart | Classification | Milestone | Notes |
|---|---|---|---|---|
| `comms/uxas-comms` | n/a (namespace root) | drop | M7 | |
| `comms/uxas-comms-data` | `Communications/MessageAttributes.h` | covered by C++ | M2 | |
| `comms/uxas-comms-data-addressed` | `Communications/AddressedMessage.h` | covered by C++ | M2 | |
| `comms/uxas-comms-data-addressed-attributed` | `Communications/AddressedAttributedMessage.*` | covered by C++ | M2 | |
| `comms/uxas-comms-data-lmcp_messages` | `Communications/LmcpMessage.h` | covered by C++ | M2 | |
| `comms/uxas-comms-lmcp_net_client` | `Communications/LmcpObjectNetworkClientBase.*` | covered by C++ | M2 | |
| `comms/uxas-comms-lmcp_object_message_receiver_pipes` | `Communications/LmcpObjectMessageReceiverPipe.*` | covered by C++ | M2 | |
| `comms/uxas-comms-lmcp_object_message_sender_pipes` | `Communications/LmcpObjectMessageSenderPipe.*` | covered by C++ | M2 | |
| `comms/uxas-comms-transport` | `Communications/TransportBase.h` | covered by C++ | M2 | |
| `comms/uxas-comms-transport-network_name` | `Communications/` bridge naming | needs port | M2 | Confirm name handling. |
| `comms/uxas-comms-transport-receiver` | `Communications/TransportReceiverBase.*` | covered by C++ | M2 | |
| `comms/uxas-comms-transport-receiver-zeromq` | `Communications/ZeroMqReceiverBase.*` | covered by C++ | M2 | |
| `comms/uxas-comms-transport-receiver-zeromq-addr_attr_msg_receivers` | `Communications/ZeroMqAddressedAttributedMessageReceiver.*` | covered by C++ | M2 | |
| `comms/uxas-comms-transport-socket_configurations` | `Communications/SocketConfiguration.h` | covered by C++ | M2 | |
| `comms/uxas-comms-transport-zeromq_fabric` | `Communications/ZeroMqFabric.*` | covered by C++ | M2 | |
| `comms/uxas-comms-transport-zeromq_sender` | `Communications/ZeroMqSenderBase.*` | covered by C++ | M2 | |
| `comms/uxas-comms-transport-zeromq_sender-addr_attr_msg_senders` | `Communications/ZeroMqAddressedAttributedMessageSender.*` | covered by C++ | M2 | |
| `comms/uxas-comms-transport-zeromq_socket_configurations` | `Communications/ZeroMqSocketConfiguration.h` | covered by C++ | M2 | |

## main

| Ada unit | C++ counterpart | Classification | Milestone | Notes |
|---|---|---|---|---|
| `main/uxas_ada` | `UxAS_Main.cpp` | needs port | M2 | Compare CLI options and startup order. |
| `main/ctrl_c_handler` | signal handling in `UxAS_Main.cpp` / `Services/ServiceManager.*` | needs port | M2 | Verify clean shutdown on SIGINT. |
| `main/ctrl_c_handler__dummy` | n/a | drop | M7 | Test/stub variant. |
| `main/ctrl_c_handler__gcov` | n/a | drop | M7 | Coverage variant. |

## services

| Ada unit | C++ counterpart | Classification | Milestone | Notes |
|---|---|---|---|---|
| `services/uxas-comms-lmcp_net_client-service` | `Services/ServiceBase.*` | covered by C++ | M2 | |
| `services/arv/automation_request_validator` | `Services/AutomationRequestValidatorService.*` | needs port | M3 | Reconcile behavioural differences via differential scenarios. |
| `services/arv/automation_request_validator_mailboxes` | same | needs port | M3 | |
| `services/arv/uxas-comms-lmcp_net_client-service-automation_request_validator_interfacing` | same | needs port | M3 | |
| `services/route_aggregator/route_aggregator` | `Services/RouteAggregatorService.*` | needs port | M4 | |
| `services/route_aggregator/route_aggregator_mailboxes` | same | needs port | M4 | |
| `services/route_aggregator/uxas-comms-lmcp_net_client-service-route_aggregator_interfacing` | same | needs port | M4 | |
| `services/atbb/algebra` | `Utilities/Algebra.*`, `AlgebraBase.h` | covered by C++ | M5 | |
| `services/atbb/assignment_tree_branch_bound` | `Services/AssignmentTreeBranchBound*.*` | needs port | M5 | |
| `services/atbb/assignment_tree_branch_bound_mailboxes` | same | needs port | M5 | |
| `services/atbb/uxas-comms-lmcp_net_client-service-assignment_tree_branch_bound_interfacing` | same | needs port | M5 | |
| `services/waypoint_manager/waypoint_plan_manager` | `Services/WaypointPlanManagerService.*` | needs port | M6 | |
| `services/waypoint_manager/waypoint_plan_manager_mailboxes` | same | needs port | M6 | |
| `services/waypoint_manager/uxas-comms-lmcp_net_client-service-waypoint_plan_manager_interfacing` | same | needs port | M6 | |
| `services/template` | `Services/00_ServiceTemplate.*` | drop | M7 | Template only. |

## spark

SPARK boundary and conversion packages exist for formal proof of the Ada services. C++ has no equivalent need.

| Ada unit | C++ counterpart | Classification | Milestone | Notes |
|---|---|---|---|---|
| `services/spark/afrl-cmasi-automationrequest-spark_boundary` | LMCP types from LmcpGen | drop | M7 | |
| `services/spark/afrl-cmasi-automationresponse-spark_boundary` | same | drop | M7 | |
| `services/spark/afrl-cmasi-lmcptask-spark_boundary` | same | drop | M7 | |
| `services/spark/afrl-cmasi-missioncommand-spark_boundary` | same | drop | M7 | |
| `services/spark/avtas-lmcp-object-spark_boundary` | same | drop | M7 | |
| `services/spark/common` | n/a | drop | M7 | |
| `services/spark/common_formal_containers` | STL containers | drop | M7 | |
| `services/spark/lmcp_message_conversions` | LMCP types from LmcpGen | drop | M7 | |
| `services/spark/lmcp_messages` | same | drop | M7 | |
| `src/ada/proof` | n/a | drop | M7 | GNATprove session files. |

## Ada tests (`src/ada/src/tests`)

| Ada unit | C++ counterpart | Classification | Milestone | Notes |
|---|---|---|---|---|
| `tests/test`, `test_attr_addr_recvr`, `test_receiver_pipes`, `test_msg_decode` | `tests/cpp/differential` scenarios | needs port | M2 | Re-express as differential scenarios. |
| `tests/test_bytebuffers` | `tests/cpp/unit/test_bytebuffers.cpp` | covered by C++ | M1 | Ported in this milestone. |
| `tests/test_configuration_manager` | GoogleTest in `tests/cpp/unit` | needs port | M2 | |

## Summary

| Classification | Rows |
|---|---|
| covered by C++ | 25 |
| needs port | 22 |
| drop | 20 |

Counts cover the table rows above (grouped test rows count once).

## Milestone consumption

| Milestone | Rows owned |
|---|---|
| M2 | utils, common, comms, main, `ServiceBase`, Ada test ports |
| M3 | `services/arv/*` |
| M4 | `services/route_aggregator/*` |
| M5 | `services/atbb/*` |
| M6 | `services/waypoint_manager/*` |
| M7 | every row classified `drop`, then removal of the Ada tree |
