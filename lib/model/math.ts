// lib/model/math.ts

export function americanToProb(odds: number): number {
  if (odds > 0) return 100 / (odds + 100)
  return Math.abs(odds) / (Math.abs(odds) + 100)
}

export function probToAmerican(p: number): number {
  if (p <= 0 || p >= 1) return 0
  if (p >= 0.5) {
    return -Math.round((p / (1 - p)) * 100)
  }
  return Math.round(((1 - p) / p) * 100)
}

export function evPercent(pModel: number, odds: number): number {
  const dec = odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds)
  return (pModel * dec - 1) * 100
}

export function randn(): number {
  let u = 0
  let v = 0
  while (u === 0) u = Math.random()
  while (v === 0) v = Math.random()
  return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v)
}

export function normalCdf(x: number): number {
  return 0.5 * (1 + erf(x / Math.SQRT2))
}

export function erf(x: number): number {
  const sign = x < 0 ? -1 : 1
  const absX = Math.abs(x)
  const a1 = 0.254829592
  const a2 = -0.284496736
  const a3 = 1.421413741
  const a4 = -1.453152027
  const a5 = 1.061405429
  const p = 0.3275911
  const t = 1 / (1 + p * absX)
  const y =
    1 -
    (((((a5 * t + a4) * t + a3) * t + a2) * t + a1) *
      t *
      Math.exp(-absX * absX))
  return sign * y
}
