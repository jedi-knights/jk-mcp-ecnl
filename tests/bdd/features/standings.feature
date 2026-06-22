Feature: ECNL standings and schedule
  As an analyst
  I want flight standings and schedules
  So that I can follow an ECNL/ECRL conference

  @smoke
  Scenario: Retrieve a flight standings table
    Given a stubbed ECNL data source
    When I request the standings for event 3933 flight 32928
    Then the standings leader is "Slammers"

  @smoke
  Scenario: Extract completed results from a flight schedule
    Given a stubbed ECNL data source
    When I request the results for event 3933 flight 32928
    Then 1 completed match is returned
