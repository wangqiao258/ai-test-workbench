import type { SchemaField } from '../../types'

export function SchemaTable({ fields }: { fields: SchemaField[] }) {
  if (!fields.length) {
    return <p className="muted-line">无字段定义</p>
  }
  return (
    <table className="mini-table">
      <thead>
        <tr>
          <th style={{ width: '24%' }}>字段</th>
          <th style={{ width: '18%' }}>类型</th>
          <th style={{ width: '10%' }}>必填</th>
          <th>说明</th>
        </tr>
      </thead>
      <tbody>
        {fields.map((field) => (
          <tr key={field.name}>
            <td>
              <code className="field-name">{field.name}</code>
            </td>
            <td>
              <span className="type-pill">{field.type}</span>
            </td>
            <td>
              {field.required ? (
                <span className="required-yes">是</span>
              ) : (
                <span className="required-no">否</span>
              )}
            </td>
            <td>{field.description}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
