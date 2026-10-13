export type Customer = {
  customer_id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string;
  gender: string;
  phone: string;
  email: string;
  city: string;
  state: string;
  country: string;
  pincode: string;
  policy_id: string;
  policy_type: string;
  policy_term_years: number;
  policy_start_date: string;
  maturity_date: string;
  claim_type: string;
  policy_status: string;
};

export type CustomerList = {
  items: Customer[];
  total: number;
  page: number;
  page_size: number;
};

export type CountItem = { name: string; count: number };

export type CustomerStats = {
  total: number;
  by_policy_type: CountItem[];
  by_status: CountItem[];
  by_city: CountItem[];
};

export type CustomerFilters = {
  search?: string;
  policy_type?: string;
  policy_status?: string;
  page?: number;
  page_size?: number;
};

export type DashboardStats = {
  policies: number;
  indexed_policies: number;
  processing_policies: number;
  failed_policies: number;
  chunks: number;
  categories: CountItem[];
};
