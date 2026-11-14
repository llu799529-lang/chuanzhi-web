import { defineStore } from "pinia";

const TOKEN_KEY = "mt_token";
const USERNAME_KEY = "mt_username";

/** 按账号保存的本地缓存（眼底 / 化验单报告）：换账号或退出登录时清掉，下一个人不会看到上一个人的报告。 */
const USER_CACHE_KEYS = ["mt.labReport", "mt_fundus_report_v7", "mt_fundus_pair_v1", "mt_fundus_report_v6"];
function clearUserCaches(): void {
  for (const k of USER_CACHE_KEYS) {
    try {
      localStorage.removeItem(k);
    } catch {
      /* 隐私模式等写不了存储的环境 */
    }
  }
}

interface AuthState {
  token: string;
  username: string;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    token: localStorage.getItem(TOKEN_KEY) ?? "",
    username: localStorage.getItem(USERNAME_KEY) ?? "",
  }),
  getters: {
    loggedIn: (s): boolean => !!s.token,
    /** 与原版一致：无用户名时显示 “用户”，头像取首字符大写 */
    displayName: (s): string => s.username || "用户",
    initial(): string {
      return this.displayName.charAt(0).toUpperCase();
    },
  },
  actions: {
    save(data: { token: string; username: string }) {
      if (this.username !== data.username) clearUserCaches();
      this.token = data.token;
      this.username = data.username;
      localStorage.setItem(TOKEN_KEY, data.token);
      localStorage.setItem(USERNAME_KEY, data.username);
    },
    clear() {
      this.token = "";
      this.username = "";
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USERNAME_KEY);
      clearUserCaches();
    },
  },
});
