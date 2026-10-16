// Rows of the monthly invoice table on the billing page.
// A month has up to ~20,000 orders; the account has ~5,000 customers.

export function invoiceRows(orders, customers) {
  return orders.map((order) => {
    const customer = customers.find((c) => c.id === order.customerId);
    return {
      id: order.id,
      customer: customer ? customer.name : "unknown",
      total: order.items.reduce((sum, item) => sum + item.price * item.quantity, 0),
    };
  });
}
