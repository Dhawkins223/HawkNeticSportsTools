// lib/model/math.ts

export function americanToDecimal(odds: number): number {
  if (!Number.isFinite(odds)) {
    throw new Error('Invalid American odds value')
  }
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds)
}

export function decimalToAmerican(decimal: number): number {
  if (decimal <= 1) {
    throw new Error('Decimal odds must be greater than 1')
  }
  if (decimal >= 2) {
    return Math.round((decimal - 1) * 100)
  }
  return Math.round(-100 / (decimal - 1))
}

export function impliedProbFromAmerican(odds: number): number {
  if (!Number.isFinite(odds)) {
    throw new Error('Invalid American odds value')
  }
  return odds > 0 ? 100 / (odds + 100) : Math.abs(odds) / (Math.abs(odds) + 100)
}

export function kellyFraction(trueProb: number, decimalOdds: number, kellyShare = 1): number {
  if (decimalOdds <= 1) {
    return 0
  }
  const edge = trueProb * decimalOdds - 1
  const divisor = decimalOdds - 1
  const fraction = edge / divisor
  if (fraction <= 0) {
    return 0
  }
  return Math.max(0, Math.min(fraction * kellyShare, 1))
}

export function normalizeProbs(values: number[]): number[] {
  const cleaned = values.map((value) => Math.max(0, value))
  const total = cleaned.reduce((sum, value) => sum + value, 0)
  if (total === 0) {
    const uniform = 1 / cleaned.length
    return cleaned.map(() => uniform)
  }
  return cleaned.map((value) => value / total)
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function logit(prob: number): number {
  return Math.log(prob / (1 - prob))
}

export function sigmoid(value: number): number {
  return 1 / (1 + Math.exp(-value))
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

export function inverseNormal(p: number): number {
  if (p <= 0 || p >= 1) {
    return p === 0 ? -Infinity : Infinity
  }
  const a = [
    -3.969683028665376e+01,
    2.209460984245205e+02,
    -2.759285104469687e+02,
    1.383577518672690e+02,
    -3.066479806614716e+01,
    2.506628277459239e+00
  ]
  const b = [
    -5.447609879822406e+01,
    1.615858368580409e+02,
    -1.556989798598866e+02,
    6.680131188771972e+01,
    -1.328068155288572e+01
  ]
  const c = [
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e+00,
    -2.549732539343734e+00,
    4.374664141464968e+00,
    2.938163982698783e+00
  ]
  const d = [
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e+00,
    3.754408661907416e+00
  ]
  const plow = 0.02425
  const phigh = 1 - plow

  let q: number
  let r: number

  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p))
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
  }
  if (phigh < p) {
    q = Math.sqrt(-2 * Math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
  }

  q = p - 0.5
  r = q * q
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
    (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
}
