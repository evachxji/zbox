/**
 * 本机设置：指纹（首启生成 32 位随机 hex）与别名，preferences 持久化。
 * 模式参考 LocalSendLite_HarmonyOS_NEXT 的 utils/ReadConfig.ets（MIT，见 harmony/NOTICE）。
 */
import { preferences } from '@kit.ArkData'
import { common } from '@kit.AbilityKit'
import { deviceInfo } from '@kit.BasicServicesKit'
import { util } from '@kit.ArkTS'
import { DeviceInfo, PROTOCOL_PORT } from '../protocol/Protocol'

let prefs: preferences.Preferences | null = null

export function initSettings(context: common.UIAbilityContext): void {
  prefs = preferences.getPreferencesSync(context, { name: 'zbox_transfer' })
  if (!prefs.hasSync('fingerprint')) {
    // 16 字节随机数 = 32 位 hex（uuid 去横线），与 Android 端指纹格式一致
    prefs.putSync('fingerprint', util.generateRandomUUID(false).replace(/-/g, ''))
    prefs.flush()
  }
}

function ensurePrefs(): preferences.Preferences {
  if (prefs === null) {
    // initSettings 必先于一切调用（EntryAbility.onCreate）
    throw new Error('Settings not initialized')
  }
  return prefs
}

export function fingerprint(): string {
  return ensurePrefs().getSync('fingerprint', '') as string
}

export function getAlias(): string {
  const saved = ensurePrefs().getSync('alias', '') as string
  if (saved.length > 0) {
    return saved
  }
  return defaultAlias()
}

export function setAlias(value: string): void {
  const p = ensurePrefs()
  p.putSync('alias', value)
  p.flush()
}

function defaultAlias(): string {
  const model = deviceInfo.marketName.length > 0 ? deviceInfo.marketName : deviceInfo.productModel
  return 'HarmonyOS-' + model
}

/** 本机 DeviceInfo（协议字段与 PC/Android 端一致） */
export function localInfo(): DeviceInfo {
  return {
    alias: getAlias(),
    version: '2.0',
    deviceModel: deviceInfo.productModel,
    deviceType: 'mobile',
    fingerprint: fingerprint(),
    port: PROTOCOL_PORT,
    protocol: 'http',
    announce: false,
  }
}