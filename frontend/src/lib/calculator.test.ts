import { describe, expect, it } from 'vitest'
import contract from '../../../backend/tests/fixtures/calculator-contract.json'
import type { CalcPayload, StaticCatalog } from '../types'
import { createCalculator, roundLikePython } from './calculator'

const catalog = contract.catalog as StaticCatalog
const calculator = createCalculator(catalog)

describe('browser forecasts match the Python calculator', () => {
  for (const scenario of contract.cases) {
    it(scenario.name, () => {
      const kind = scenario.kind as 'estimate' | 'cascade'
      expect(calculator[kind](scenario.payload as CalcPayload)).toEqual(scenario.expected)
    })
  }
})

describe('forecast validation and precision', () => {
  it('rounds ties and binary decimal values as the backend does', () => {
    expect([2.5, 3.5, 0.5].map((value) => roundLikePython(value))).toEqual([2, 4, 0])
    expect([1.125, 1.375, 2.675, 1.005].map((value) => roundLikePython(value, 2))).toEqual([1.12, 1.38, 2.67, 1])
  })
  it('rejects invalid targets, research vehicles, and non-finite pace', () => {
    const payload = contract.cases[0].payload as CalcPayload
    expect(() => calculator.estimate({ ...payload, vehicle_id: -1 })).toThrow('Vehicle not found')
    expect(() => calculator.estimate({ ...payload, research_vehicle_id: payload.vehicle_id })).toThrow('target cannot')
    expect(() => calculator.estimate({ ...payload, avg_rp_per_battle: NaN })).toThrow('valid')
    expect(() => calculator.estimate({ ...payload, booster_percent: 2000 })).toThrow('valid')
  })
})
