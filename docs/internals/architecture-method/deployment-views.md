# Deployment View Method

## Status

- Authority: normative — supporting method for deployment views
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

Use this method to connect logical responsibilities to execution carriers and
to test that placement supports the accepted contracts. Follow the
[canonical method](README.md), [review method](architecture-review.md) and
[deployment template](templates/deployment.md). Small scopes may use a single
mapping table; expand only where distribution, isolation or lifecycle matters.

## Frame The View

Identify the governed scope, deployment environment/profile, revision and
question. Distinguish development, test, production or other relevant variants
from geographic location. Label accepted placement constraints, candidate
designs and observed Current instances separately; a drawn topology is not
evidence that it exists or meets a quality target.

The physical system context keeps the scope a black box, identifying external
people, agents, systems, access paths and environmental constraints. The
deployment view expands how the scope is carried internally and connects back
to those same boundaries. Software-to-infrastructure mapping and nested nodes
are also used by [arc42](https://docs.arc42.org/section-7/) and
[C4 deployment views](https://c4model.com/diagrams/deployment).

## Locations, Zones And Nodes

| Element | Meaning and minimum information |
| --- | --- |
| Location | Where execution takes place: for example a region, site, edge installation or user device location. Give identity, relevant parent/location relationships and constraints. |
| Zone | A grouping or isolation boundary. State its type and purpose, membership, owner and allowed cross-zone interactions. Distinguish network, trust, failure and administrative boundaries. |
| Node | A concrete or explicitly abstract carrier: host, VM, OS container, process or managed execution environment. State its type, containing/running-on node where relevant, location/zone membership and resource/lifecycle responsibility. |

Keep concise location and zone lists. Different zone types may overlap and need
not form one tree: being in separate trust zones does not prove independent
failure domains. State which memberships or constraints follow from node
containment and which need separate evidence.

Cloud usually identifies an environment or resource grouping; show the actual
managed service, host or runtime that carries the software where known. If only
an abstract carrier is known, label the unknowns and make no unsupported isolation
or capacity claim. Hosts, VMs, OS containers and processes may be nested; not
every diagram needs every level. Distinguish an OS container from any broader
use of the word container in other modeling notations.

Label edges by meaning, such as contains, runs-on, deployed-to or communicates-with.
Do not infer runtime communication or independence from visual grouping alone.

## Components, Deployment Units And Instances

Use the mapping **logical component -> deployment unit -> runtime instance ->
carrier node** when the intermediate distinctions matter. A deployment unit is
a running part that needs separate expression for placement, scaling or lifecycle
management. The runtime instance is a concrete occurrence/replica of that unit.
Simple views can collapse these distinctions while retaining an unambiguous
mapping to logical responsibilities.

A component may map to several units, a unit may realize several components,
and a unit may have several instances across zones. Record the responsibilities
covered by each mapping. A packaging boundary, process boundary and logical
component boundary are not automatically identical.

Optional unit roles help explain placement:

| Role | Typical responsibility |
| --- | --- |
| IO | Access, protocol communication and input/output |
| Control | Coordination, scheduling, policy and lifecycle control |
| Compute | Calculation, transformation and task execution |
| Data | Storage, indexing, queries and replication |

Roles may overlap; do not require four units per component. Split only when
placement, resource, permission, scaling or failure requirements justify it.
Link Data units to the [data model](domain-data-modeling.md) and component CRUD
responsibilities: storing bytes does not grant authority over the business fact.

## Placement And Communication Constraints

For significant units and relationships, record:

- allowed/required locations, zone types and node capabilities, with reasons
  linked to requirements or ARDs;
- replica/scaling expectations and required co-location or separation;
- shared storage, control services and other dependencies that affect resource
  limits or failure behavior;
- endpoint and connection direction, protocol, identity/authority, relevant
  resource or latency limits, and expected failure/cancellation behavior;
- who starts, stops, upgrades and recovers the unit, including compatibility
  during overlapping versions when relevant.

Dynamic scheduling may specify placement constraints instead of fixed instance
addresses. Link observed inventories as Current evidence rather than manually
maintaining changing host lists in accepted design. Environmental variants can
share a baseline with explicit differences; a test profile validates only the
conditions it actually represents.

## Map Physical Context To Deployment And Scenarios

Reuse canonical IDs or links for actors, locations, zones, nodes, ports and
connections across views. Where a context object expands into several deployment
objects, provide the mapping instead of creating unrelated names. Mark external
carriers as context dependencies; their presence in a diagram grants no local
deployment authority.

For each important scenario, connect:

**use case / quality scenario -> external actor and physical context connection
-> boundary port -> responsible component/unit -> instance or placement class
-> carrier and zones -> collaborating units or external dependencies**.

Trace responses and data changes as well as incoming requests. Event-driven,
scheduled or maintenance scenarios may start inside the scope; say so rather
than inventing an external actor. Check that significant context relationships
have a deployment realization and significant deployment communications have a
governing interaction/contract. Internal links need not appear on the black-box
context graph, but must connect to the internal design.

A short mapping table can link scenario/step, context port/connection,
component/unit, node/zone and contract/evidence. Reuse those references in
walkthrough records rather than duplicating complete topologies.

## Deployment-Aware Walkthrough And Review

Apply the [scenario walkthrough](architecture-review.md#scenario-walkthrough)
to the chosen environment/profile and revision. Overlay significant logical
steps on their actual or intended placement, then check relevant concerns:

| Review concern | Questions and evidence |
| --- | --- |
| Mapping and reachability | Can the modeled caller reach the intended port through the stated connections? Do physical actor, component and node mappings agree? |
| Authority and isolation | Where is identity/permission checked? Which trust boundaries are crossed? Is claimed isolation supported by the carrier and configuration? |
| Resources and performance | Are workload, queueing, network and shared-resource costs included? Does placement support the end-to-end quality scenario? |
| Failure and recovery | What if a process, host, zone or connection fails? Which shared dependencies remain, who recovers, and what does the caller observe? |
| Data behavior | Where are authoritative and derived values held? Do cross-zone communication, replication and recovery preserve accepted consistency/retention rules? |
| Evolution and operation | Can placement, scaling, restart or upgrade change ordering, version compatibility, ownership or observable behavior? |

For example, trace a request arriving through an external connection to an IO
unit and then a Compute unit on another node. If that node fails after a side
effect but before its response, identify who owns the result, retry decision and
recovery. Separate replicas do not prove availability if they depend on the
same unavailable storage or control service. This illustrates review questions,
not a prescribed topology or recovery mechanism.

Record missing mappings, unverified environmental assumptions and contradictory
contracts as existing review findings with evidence, owners and closure actions.
Human and AI reviewers must not invent routes, credentials, failover or replica
independence to complete a walkthrough. Design analysis does not establish
runtime reachability, isolation, throughput or recovery without matching evidence.

## Placement, Maintenance And Completion

Maintain `deployment.md` or a section in the owning scope; a system-wide AOD view
may summarize and link it. Keep contracts, key mechanisms and decisions in their
canonical artifacts. Do not duplicate detailed physical context or generated
instance inventories. Acceptance identifies the reviewed placement constraints,
environment/profile and scope, independently of implementation status.

When placement, connections, trust/resource/failure boundaries or deployment
variants change, review affected physical context, component interactions,
data mappings, quality criteria and walkthrough paths together. Update affected
references and Current/Target deltas, reusing unchanged evidence. The view is
ready when important mappings and constraints are clear, required decisions are
accepted and blocking findings are closed; pending implementation verification
remains explicit.
